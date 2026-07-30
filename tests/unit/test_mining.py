import pytest
from datetime import datetime, timedelta
from src.mining.cluster_engine import (
    ClusterEngine,
    EmbeddingClusterEngine,
    _tokenize,
    jaccard_similarity,
    _significant_tokens,
    token_cosine_similarity,
    _extract_error_type,
)
from src.mining.pattern_detector import compute_velocity


class TestTokenization:
    def test_tokenize_basic(self):
        tokens = _tokenize("Connection timeout to database")
        assert "connection" in tokens
        assert "timeout" in tokens
        assert "database" in tokens

    def test_tokenize_stopwords_removed(self):
        tokens = _tokenize("The error was connection timeout")
        assert "the" not in tokens
        assert "error" not in tokens

    def test_tokenize_case_insensitive(self):
        tokens = _tokenize("CONNECTION TIMEOUT")
        assert "connection" in tokens
        assert "timeout" in tokens


class TestJaccardSimilarity:
    def test_identical_sets(self):
        sim = jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"})
        assert sim == 1.0

    def test_disjoint_sets(self):
        sim = jaccard_similarity({"a", "b"}, {"c", "d"})
        assert sim == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert sim == 0.5

    def test_empty_sets(self):
        assert jaccard_similarity(set(), {"a"}) == 0.0
        assert jaccard_similarity({"a"}, set()) == 0.0
        assert jaccard_similarity(set(), set()) == 0.0


class TestSignificantTokens:
    def test_basic_extraction(self):
        tokens = _significant_tokens("Connection timeout to database")
        assert "connection" in tokens
        assert "timeout" in tokens
        assert "database" in tokens
        assert "to" not in tokens

    def test_stopwords_removed(self):
        tokens = _significant_tokens("The error was a failed exception")
        assert len(tokens) == 0 or all(t not in tokens for t in ["the", "error", "was", "failed", "exception"])

    def test_short_tokens_removed(self):
        tokens = _significant_tokens("ab cd ef")
        assert len(tokens) == 0


class TestTokenTFIDFSimilarity:
    def test_identical(self):
        a = {"db": 1.0, "timeout": 0.8}
        b = {"db": 1.0, "timeout": 0.8}
        assert token_cosine_similarity(a, b) == pytest.approx(1.0, rel=0.01)

    def test_no_overlap(self):
        a = {"db": 1.0}
        b = {"network": 1.0}
        assert token_cosine_similarity(a, b) == 0.0

    def test_partial(self):
        a = {"db": 1.0, "timeout": 0.8, "connection": 0.6}
        b = {"db": 1.0, "timeout": 0.9, "refused": 0.7}
        sim = token_cosine_similarity(a, b)
        assert 0.0 < sim < 1.0

    def test_empty(self):
        assert token_cosine_similarity({}, {"a": 1.0}) == 0.0


class TestExtractErrorType:
    def test_connection_timeout(self):
        assert _extract_error_type("Connection timeout") == "Connection/Timeout"

    def test_connection_refused(self):
        assert _extract_error_type("Connection refused") == "Connection Refused"

    def test_auth_error(self):
        assert _extract_error_type("Authentication failed") == "Authentication/Authorization"
        assert _extract_error_type("Permission denied") == "Authentication/Authorization"

    def test_not_found(self):
        assert _extract_error_type("Not found") == "Not Found"
        assert _extract_error_type("404 error") == "Not Found"

    def test_memory_error(self):
        assert _extract_error_type("OutOfMemoryError") == "Memory"
        assert _extract_error_type("heap space") == "Memory"

    def test_null_reference(self):
        assert _extract_error_type("NullPointerException") == "Null Reference"
        assert _extract_error_type("undefined is not a function") == "Null Reference"

    def test_unknown(self):
        assert _extract_error_type("Something random happened") == "Other"


class TestComputeVelocity:
    def test_positive_velocity(self):
        data = {"2026-07-20": 1, "2026-07-21": 3, "2026-07-22": 5, "2026-07-23": 8}
        vel = compute_velocity(data)
        assert vel > 0

    def test_negative_velocity(self):
        data = {"2026-07-20": 10, "2026-07-21": 7, "2026-07-22": 4, "2026-07-23": 1}
        vel = compute_velocity(data)
        assert vel < 0

    def test_flat_velocity(self):
        data = {"2026-07-20": 5, "2026-07-21": 5, "2026-07-22": 5}
        vel = compute_velocity(data)
        assert abs(vel) < 0.01

    def test_insufficient_data(self):
        assert compute_velocity({"2026-07-20": 5}) == 0.0
        assert compute_velocity({"2026-07-20": 5, "2026-07-21": 7}) == 0.0


class TestClusterEngine:
    def test_empty_events(self):
        engine = ClusterEngine()
        assert engine.cluster_events([]) == []

    def test_single_event(self):
        engine = ClusterEngine()
        events = [{"error_message": "Connection timeout to database"}]
        clusters = engine.cluster_events(events)
        assert len(clusters) == 1
        assert clusters[0]["size"] == 1
        assert clusters[0]["is_noise"] is True

    def test_similar_events_cluster_together(self):
        engine = ClusterEngine(similarity_threshold=0.30)
        events = [
            {"error_message": "Connection timeout to database: timeout after 30s"},
            {"error_message": "DB connection timeout: connection refused after timeout"},
            {"error_message": "Authentication failed: invalid credentials"},
        ]
        clusters = engine.cluster_events(events)
        assert len(clusters) >= 2
        db_clusters = [c for c in clusters if "Connection" in c.get("error_type", "")]
        assert any(c["size"] >= 2 for c in db_clusters)

    def test_dissimilar_events_separate_clusters(self):
        engine = ClusterEngine(similarity_threshold=0.50)
        events = [
            {"error_message": "Connection timeout to database server"},
            {"error_message": "Disk space warning: 85% full on volume"},
        ]
        clusters = engine.cluster_events(events)
        assert len(clusters) >= 2

    def test_cluster_metadata(self):
        engine = ClusterEngine()
        ts = datetime.utcnow().isoformat()
        events = [
            {"error_message": "Connection timeout to database", "service_name": "payment-service", "severity": "CRITICAL", "timestamp": ts},
            {"error_message": "DB timeout: connection refused", "service_name": "payment-service", "severity": "HIGH", "timestamp": ts},
        ]
        clusters = engine.cluster_events(events)
        c = clusters[0]
        assert c["size"] == 2
        assert "payment-service" in c["services"]
        assert c["member_count"] == 2
        assert len(c["members"]) == 2

    def test_noise_flag(self):
        engine = ClusterEngine()
        events = [
            {"error_message": "Unique error that has no similar events ever"},
        ]
        clusters = engine.cluster_events(events)
        assert clusters[0]["is_noise"] is True


class TestEmbeddingClusterEngine:
    def test_fallback_on_missing_embedder(self):
        engine = EmbeddingClusterEngine()
        events = [
            {"error_message": "Connection timeout to database"},
            {"error_message": "Authentication failed"},
        ]
        import asyncio
        clusters = asyncio.run(engine.cluster_events(events))
        assert len(clusters) >= 2


class TestPatternDetectorIntegration:
    def test_velocity_analysis(self):
        from src.mining.pattern_detector import PatternDetector
        detector = PatternDetector()
        clusters = [
            {
                "cluster_id": 0,
                "error_type": "Connection/Timeout",
                "members": [
                    {"timestamp": (datetime.utcnow() - timedelta(days=i)).isoformat(),
                     "error_message": "timeout"}
                    for i in range(5, 0, -1)
                ],
            }
        ]
        result = detector._compute_velocity_analysis(clusters)
        assert len(result) == 1
        assert result[0]["cluster_id"] == 0
        assert result[0]["total_occurrences"] == 5

    def test_service_matrix(self):
        from src.mining.pattern_detector import PatternDetector
        detector = PatternDetector()
        clusters = [
            {
                "cluster_id": 0,
                "error_type": "Connection/Timeout",
                "members": [
                    {"service_name": "payment-service"},
                    {"service_name": "payment-service"},
                    {"service_name": "order-service"},
                ],
            }
        ]
        matrix = detector._compute_service_matrix(clusters)
        payment = [m for m in matrix if m["service"] == "payment-service"]
        assert len(payment) > 0
