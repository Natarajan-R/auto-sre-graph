import pytest
from src.mining.forecaster import (
    ExponentialSmoother,
    DoubleExponentialSmoother,
    compute_moving_average,
    forecast_cluster,
    compute_page_risk_score,
    rank_clusters_by_risk,
    _risk_label,
    _validate_series,
)
from src.mining.predictor import RunbookMatcher


class TestValidateSeries:
    def test_empty(self):
        assert _validate_series([]) == [0.0]

    def test_all_none(self):
        assert _validate_series([None, None]) == [0.0, 0.0]

    def test_mixed(self):
        result = _validate_series([1.0, None, 3.0])
        assert result == [1.0, 0.0, 3.0]

    def test_all_zero(self):
        assert _validate_series([0.0, 0.0]) == [0.0, 0.0]

    def test_normal(self):
        assert _validate_series([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


class TestExponentialSmoother:
    def test_alpha_clamped(self):
        s = ExponentialSmoother(alpha=2.0)
        assert 0.01 <= s.alpha <= 0.99

    def test_alpha_clamped_low(self):
        s = ExponentialSmoother(alpha=-1.0)
        assert s.alpha == 0.01

    def test_single_value(self):
        s = ExponentialSmoother(alpha=0.3)
        result = s.fit_predict([5.0], steps=3)
        assert result == [5.0, 5.0, 5.0]

    def test_empty(self):
        s = ExponentialSmoother()
        result = s.fit_predict([], steps=4)
        assert result == [0.0, 0.0, 0.0, 0.0]

    def test_increasing_values(self):
        s = ExponentialSmoother(alpha=0.5)
        result = s.fit_predict([1.0, 2.0, 3.0, 4.0, 5.0], steps=3)
        assert len(result) == 3
        assert all(r > 0 for r in result)
        assert result[0] == result[1]

    def test_flat_values(self):
        s = ExponentialSmoother(alpha=0.3)
        result = s.fit_predict([10.0, 10.0, 10.0], steps=2)
        assert result == [10.0, 10.0]


class TestDoubleExponentialSmoother:
    def test_single_value(self):
        s = DoubleExponentialSmoother()
        result = s.fit_predict([5.0], steps=3)
        assert result == [5.0, 5.0, 5.0]

    def test_empty(self):
        s = DoubleExponentialSmoother()
        result = s.fit_predict([], steps=3)
        assert result == [0.0, 0.0, 0.0]

    def test_increasing_forecasts_higher(self):
        s = DoubleExponentialSmoother(alpha=0.5, beta=0.3)
        result = s.fit_predict([1.0, 2.0, 3.0, 4.0, 5.0], steps=4)
        assert len(result) == 4
        assert result[-1] > result[0]

    def test_decreasing_forecasts_lower(self):
        s = DoubleExponentialSmoother(alpha=0.5, beta=0.3)
        result = s.fit_predict([10.0, 8.0, 6.0, 4.0], steps=3)
        assert len(result) == 3
        assert all(r >= 0 for r in result)

    def test_beta_clamped(self):
        s = DoubleExponentialSmoother(beta=2.0)
        assert s.beta == 0.99
        s2 = DoubleExponentialSmoother(beta=-1.0)
        assert s2.beta == 0.01


class TestComputeMovingAverage:
    def test_basic(self):
        result = compute_moving_average([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
        assert len(result) == 5
        assert result[-1] == pytest.approx(4.0, rel=0.1)

    def test_short_series(self):
        result = compute_moving_average([5.0], window=3)
        assert result == [5.0]

    def test_empty(self):
        assert compute_moving_average([]) == [0.0]


class TestForecastCluster:
    def test_empty_history(self):
        result = forecast_cluster([], steps=24)
        assert result["forecast"] == [0.0] * 24
        assert result["trend_direction"] == "unknown"

    def test_rising_trend(self):
        history = [{"size": 8}, {"size": 5}, {"size": 3}, {"size": 1}]
        result = forecast_cluster(history, steps=8)
        assert len(result["forecast"]) == 8
        assert result["peak"] > 0
        assert result["trend_direction"] in ("rising", "stable")

    def test_falling_trend(self):
        history = [{"size": 5}, {"size": 10}, {"size": 15}, {"size": 20}]
        result = forecast_cluster(history, steps=8)
        assert result["trend_direction"] == "falling"

    def test_single_entry(self):
        history = [{"size": 7}]
        result = forecast_cluster(history, steps=4)
        assert result["last_observed"] == 7.0
        assert len(result["forecast"]) == 4

    def test_simple_method(self):
        history = [{"size": 1}, {"size": 2}, {"size": 3}]
        result = forecast_cluster(history, steps=3, method="simple")
        assert len(result["forecast"]) == 3


class TestPageRiskScore:
    def test_high_velocity(self):
        cluster = {"velocity": 4.0, "trend": "accelerating", "size": 40, "is_noise": False}
        fc = {"peak": 60.0}
        score = compute_page_risk_score(cluster, fc, cascade_count=5)
        assert score >= 0.5

    def test_low_risk(self):
        cluster = {"velocity": 0.1, "trend": "stable", "size": 1, "is_noise": True}
        fc = {"peak": 1.0}
        score = compute_page_risk_score(cluster, fc)
        assert score < 0.3

    def test_cascade_boost(self):
        cluster = {"velocity": 0.5, "trend": "stable", "size": 5, "is_noise": False}
        fc = {"peak": 5.0}
        score_high = compute_page_risk_score(cluster, fc, cascade_count=10)
        score_low = compute_page_risk_score(cluster, fc, cascade_count=0)
        assert score_high > score_low

    def test_forecast_peak_boost(self):
        cluster = {"velocity": 0.5, "trend": "stable", "size": 10, "is_noise": False}
        fc = {"peak": 30.0}
        score = compute_page_risk_score(cluster, fc)
        assert score > 0.3

    def test_score_bounds(self):
        for _ in range(10):
            cluster = {"velocity": 5.0, "trend": "accelerating", "size": 100, "is_noise": False}
            fc = {"peak": 200.0}
            score = compute_page_risk_score(cluster, fc, cascade_count=20)
            assert 0.0 <= score <= 1.0


class TestRankClustersByRisk:
    def test_empty(self):
        assert rank_clusters_by_risk([], {}) == []

    def test_single_cluster(self):
        clusters = [{"cluster_id": 0, "error_type": "Timeout", "size": 5, "velocity": 0.0, "trend": "stable", "is_noise": False, "services": ["api"]}]
        ranked = rank_clusters_by_risk(clusters, {0: [{"size": 5}]})
        assert len(ranked) == 1
        assert ranked[0]["cluster_id"] == 0
        assert "page_risk_score" in ranked[0]
        assert "page_risk_label" in ranked[0]

    def test_ordering(self):
        clusters = [
            {"cluster_id": 0, "error_type": "High", "size": 50, "velocity": 5.0, "trend": "accelerating", "is_noise": False, "services": ["api"]},
            {"cluster_id": 1, "error_type": "Low", "size": 1, "velocity": 0.0, "trend": "stable", "is_noise": True, "services": ["web"]},
        ]
        history = {
            0: [{"size": 10}, {"size": 30}, {"size": 50}],
            1: [{"size": 1}],
        }
        ranked = rank_clusters_by_risk(clusters, history, cascade_map={0: 5})
        assert ranked[0]["cluster_id"] == 0
        assert ranked[0]["page_risk_score"] > ranked[1]["page_risk_score"]

    def test_cascade_impact(self):
        clusters = [
            {"cluster_id": 0, "error_type": "A", "size": 10, "velocity": 0.0, "trend": "stable", "is_noise": False, "services": ["api"]},
        ]
        ranked_with = rank_clusters_by_risk(clusters, {0: [{"size": 10}]}, cascade_map={0: 10})
        ranked_without = rank_clusters_by_risk(clusters, {0: [{"size": 10}]})
        assert ranked_with[0]["page_risk_score"] >= ranked_without[0]["page_risk_score"]


class TestRiskLabel:
    def test_critical(self):
        assert _risk_label(0.85) == "critical"
        assert _risk_label(0.7) == "critical"

    def test_high(self):
        assert _risk_label(0.5) == "high"
        assert _risk_label(0.4) == "high"

    def test_medium(self):
        assert _risk_label(0.3) == "medium"
        assert _risk_label(0.2) == "medium"

    def test_low(self):
        assert _risk_label(0.1) == "low"
        assert _risk_label(0.0) == "low"


class TestRunbookMatcher:
    def test_suggest_timeout(self):
        matcher = RunbookMatcher()
        suggestions = matcher.suggest("Connection timeout to database after 30 seconds")
        assert len(suggestions) >= 1
        assert suggestions[0]["similarity"] > 0
        assert "Connection/Timeout" in [s["error_type"] for s in suggestions]

    def test_suggest_auth(self):
        matcher = RunbookMatcher()
        suggestions = matcher.suggest("Authentication failed: invalid credentials for user")
        assert len(suggestions) >= 1
        types = [s["error_type"] for s in suggestions]
        assert any("Auth" in t for t in types)

    def test_suggest_memory(self):
        matcher = RunbookMatcher()
        suggestions = matcher.suggest("OutOfMemoryError: Java heap space")
        assert len(suggestions) >= 1
        types = [s["error_type"] for s in suggestions]
        assert "Memory" in types

    def test_empty_message(self):
        matcher = RunbookMatcher()
        suggestions = matcher.suggest("")
        assert suggestions == []

    def test_unknown_error(self):
        matcher = RunbookMatcher()
        suggestions = matcher.suggest("xylophone driver not initialized in hypervisor")
        assert len(suggestions) == 0

    def test_custom_runbook(self):
        matcher = RunbookMatcher(custom_runbooks={"CustomError": "Check the custom thing"})
        assert matcher.get_runbook("CustomError") == "Check the custom thing"
        assert "Connection/Timeout" in matcher.list_runbooks()

    def test_add_runbook(self):
        matcher = RunbookMatcher()
        matcher.add_runbook("NewError", "New runbook content")
        assert matcher.get_runbook("NewError") == "New runbook content"

    def test_get_runbook_missing(self):
        matcher = RunbookMatcher()
        assert matcher.get_runbook("NonExistent") is None

    def test_list_runbooks(self):
        matcher = RunbookMatcher()
        rbs = matcher.list_runbooks()
        assert "Connection/Timeout" in rbs
        assert "Memory" in rbs
        assert len(rbs) >= 9
