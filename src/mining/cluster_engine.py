import logging
import re
import math
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> Set[str]:
    text = text.lower()
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text))
    stopwords = {
        "the", "this", "that", "with", "from", "been", "after",
        "error", "failed", "failure", "exception",
    }
    return tokens - stopwords


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _significant_tokens(error_message: str) -> Dict[str, float]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", error_message.lower())
    stopwords = {
        "the", "this", "that", "with", "from", "been", "after",
        "was", "has", "have", "had", "not", "are", "were",
        "error", "failed", "failure", "exception",
    }
    filtered = [t for t in tokens if t not in stopwords and len(t) > 2]
    if not filtered:
        return {}
    counter = Counter(filtered)
    max_freq = max(counter.values())
    return {tok: freq / max_freq for tok, freq in counter.items()}


def token_cosine_similarity(a_tokens: Dict[str, float], b_tokens: Dict[str, float]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    common = set(a_tokens) & set(b_tokens)
    if not common:
        return 0.0
    dot_product = sum(a_tokens[t] * b_tokens[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a_tokens.values()))
    norm_b = math.sqrt(sum(v * v for v in b_tokens.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _extract_error_type(msg: str) -> str:
    patterns = [
        (r"(?i)(refused|reset|unreachable)", "Connection Refused"),
        (r"(?i)(connection|timeout|connect)", "Connection/Timeout"),
        (r"(?i)(auth|permission|denied|forbidden)", "Authentication/Authorization"),
        (r"(?i)(not found|404|missing)", "Not Found"),
        (r"(?i)(memory|oom|heap)", "Memory"),
        (r"(?i)(null|undefined|NoneType)", "Null Reference"),
        (r"(?i)(disk|space|storage)", "Storage"),
        (r"(?i)(cpu|load|throttl)", "CPU/Throttling"),
        (r"(?i)(ssl|cert|tls)", "SSL/TLS"),
        (r"(?i)(dns|resolve|host)", "DNS"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, msg):
            return label
    return "Other"


class ClusterEngine:
    def __init__(self, similarity_threshold: float = 0.35):
        self.similarity_threshold = similarity_threshold

    def cluster_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not events:
            return []

        clusters: List[List[Dict[str, Any]]] = []
        cluster_tokens: List[Dict[str, float]] = []

        for event in events:
            msg = event.get("error_message", "")
            tokens = _significant_tokens(msg)

            best_idx = -1
            best_score = 0.0

            for i, ct in enumerate(cluster_tokens):
                score = token_cosine_similarity(tokens, ct)
                if score > best_score:
                    best_score = score
                    best_idx = i

            if best_idx >= 0 and best_score >= self.similarity_threshold:
                clusters[best_idx].append(event)
                for tok, weight in tokens.items():
                    if tok in cluster_tokens[best_idx]:
                        cluster_tokens[best_idx][tok] = max(cluster_tokens[best_idx][tok], weight)
                    else:
                        cluster_tokens[best_idx][tok] = weight
            else:
                clusters.append([event])
                cluster_tokens.append(tokens)

        result = []
        for idx, members in enumerate(clusters):
            error_count = len(members)
            if error_count == 0:
                continue

            top_error = max(members, key=lambda e: len(e.get("error_message", "")))
            services = list(set(m.get("service_name", "unknown") for m in members))
            severities = list(set(m.get("severity", "HIGH") for m in members))
            timestamps = [
                m.get("timestamp") for m in members
                if m.get("timestamp")
            ]

            first_seen = min(timestamps) if timestamps else None
            last_seen = max(timestamps) if timestamps else None

            error_type = _extract_error_type(top_error.get("error_message", ""))

            result.append({
                "cluster_id": idx,
                "size": error_count,
                "error_type": error_type,
                "representative_error": top_error.get("error_message", "")[:200],
                "services": services,
                "severities": severities,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "is_noise": error_count < 2,
                "members": members[:10],
                "member_count": error_count,
            })

        result.sort(key=lambda c: c["size"], reverse=True)
        for i, c in enumerate(result):
            c["cluster_id"] = i

        logger.info(
            f"Clustered {len(events)} events into {len(result)} groups "
            f"(threshold={self.similarity_threshold})"
        )
        return result


class EmbeddingClusterEngine:
    def __init__(self, similarity_threshold: float = 0.75):
        self.similarity_threshold = similarity_threshold
        self._embedder = None

    async def _get_embedder(self):
        if self._embedder is None:
            try:
                from src.context.embeddings import EmbeddingProvider
                self._embedder = EmbeddingProvider()
            except Exception as e:
                logger.warning(f"EmbeddingProvider unavailable: {e}")
                return None
        return self._embedder

    async def cluster_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        embedder = await self._get_embedder()
        if embedder is None:
            logger.info("EmbeddingProvider unavailable, falling back to text-based clustering")
            fallback = ClusterEngine(similarity_threshold=0.35)
            return fallback.cluster_events(events)

        texts = [e.get("error_message", "") for e in events]
        try:
            embeddings = await embedder.generate_batch(texts)
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}, using text fallback")
            fallback = ClusterEngine(similarity_threshold=0.35)
            return fallback.cluster_events(events)

        clusters = self._cluster_embeddings(events, embeddings)
        return clusters

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _cluster_embeddings(
        self, events: List[Dict[str, Any]], embeddings: List[List[float]]
    ) -> List[Dict[str, Any]]:
        clusters: List[List[int]] = []
        cluster_centroids: List[List[float]] = []

        for i, emb in enumerate(embeddings):
            best_idx = -1
            best_score = 0.0

            for j, centroid in enumerate(cluster_centroids):
                score = self._cosine_similarity(emb, centroid)
                if score > best_score:
                    best_score = score
                    best_idx = j

            if best_idx >= 0 and best_score >= self.similarity_threshold:
                clusters[best_idx].append(i)
                n = len(clusters[best_idx])
                centroid = cluster_centroids[best_idx]
                for k in range(len(centroid)):
                    centroid[k] = centroid[k] + (emb[k] - centroid[k]) / n
            else:
                clusters.append([i])
                cluster_centroids.append(emb[:])

        result = []
        for idx, member_indices in enumerate(clusters):
            members = [events[i] for i in member_indices]
            error_count = len(members)
            if error_count == 0:
                continue

            top_error = max(members, key=lambda e: len(e.get("error_message", "")))
            services = list(set(m.get("service_name", "unknown") for m in members))
            timestamps = [m.get("timestamp") for m in members if m.get("timestamp")]
            error_type = _extract_error_type(top_error.get("error_message", ""))

            result.append({
                "cluster_id": idx,
                "size": error_count,
                "error_type": error_type,
                "representative_error": top_error.get("error_message", "")[:200],
                "services": services,
                "first_seen": min(timestamps) if timestamps else None,
                "last_seen": max(timestamps) if timestamps else None,
                "is_noise": error_count < 2,
                "members": members[:10],
                "member_count": error_count,
            })

        result.sort(key=lambda c: c["size"], reverse=True)
        for i, c in enumerate(result):
            c["cluster_id"] = i

        logger.info(
            f"Embedding-clustered {len(events)} events into {len(result)} groups"
        )
        return result
