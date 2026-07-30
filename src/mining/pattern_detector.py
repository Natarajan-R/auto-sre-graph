import logging
import statistics
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, Counter
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def compute_velocity(daily_counts: Dict[str, int]) -> float:
    if len(daily_counts) < 3:
        return 0.0
    days = sorted(daily_counts.keys())
    x = list(range(len(days)))
    y = [daily_counts[d] for d in days]
    n = len(x)
    if n < 2:
        return 0.0
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    if den == 0:
        return 0.0
    return round(num / den, 4)


class PatternDetector:
    def __init__(self, cascade_window_minutes: int = 5):
        self.cascade_window = cascade_window_minutes

    def analyze_clusters(
        self, clusters: List[Dict[str, Any]], events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:

        patterns = {
            "velocity_analysis": self._compute_velocity_analysis(clusters),
            "cascade_roots": self._find_cascade_roots(clusters, events),
            "co_occurrence": self._compute_co_occurrence(clusters, events),
            "hourly_heatmap": self._compute_hourly_heatmap(events),
            "service_cluster_matrix": self._compute_service_matrix(clusters),
        }
        return patterns

    def _compute_velocity_analysis(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for cluster in clusters[:10]:
            members = cluster.get("members", [])
            daily: Dict[str, int] = defaultdict(int)
            for m in members:
                ts = m.get("timestamp")
                if ts:
                    day = ts[:10]
                    daily[day] += 1

            velocity = compute_velocity(dict(daily))
            total = len(members)
            avg_daily = total / max(len(daily), 1)

            if velocity > 0.5:
                trend = "accelerating"
            elif velocity < -0.5:
                trend = "declining"
            else:
                trend = "stable"

            result.append({
                "cluster_id": cluster.get("cluster_id"),
                "error_type": cluster.get("error_type", "Unknown"),
                "representative_error": cluster.get("representative_error", "")[:120],
                "total_occurrences": total,
                "unique_days": len(daily),
                "avg_daily": round(avg_daily, 1),
                "velocity": velocity,
                "trend": trend,
            })

        return result

    def _find_cascade_roots(
        self, clusters: List[Dict[str, Any]], events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        event_cluster_map: Dict[str, int] = {}
        for c in clusters:
            for m in c.get("members", []):
                tid = m.get("thread_id") or m.get("alert_id")
                if tid:
                    event_cluster_map[tid] = c["cluster_id"]

        sorted_events = sorted(
            [e for e in events if e.get("timestamp")],
            key=lambda e: e["timestamp"],
        )

        window_seconds = self.cascade_window * 60
        cascade_pairs: Dict[Tuple[int, int], int] = defaultdict(int)

        for i in range(len(sorted_events)):
            e1 = sorted_events[i]
            c1 = event_cluster_map.get(e1.get("thread_id") or e1.get("alert_id"))
            if c1 is None:
                continue
            t1 = e1["timestamp"]

            for j in range(i + 1, len(sorted_events)):
                e2 = sorted_events[j]
                t2 = e2["timestamp"]
                if isinstance(t1, str):
                    try:
                        t1_dt = datetime.fromisoformat(t1)
                        t2_dt = datetime.fromisoformat(t2)
                    except Exception:
                        continue
                else:
                    continue

                diff = (t2_dt - t1_dt).total_seconds()
                if diff > window_seconds:
                    break
                if diff < 0:
                    continue

                c2 = event_cluster_map.get(e2.get("thread_id") or e2.get("alert_id"))
                if c2 is None or c1 == c2:
                    continue
                cascade_pairs[(c1, c2)] += 1

        pair_details = []
        for (c1, c2), count in sorted(cascade_pairs.items(), key=lambda x: -x[1]):
            if count < 2:
                continue
            pair_details.append({
                "upstream_cluster_id": c1,
                "downstream_cluster_id": c2,
                "upstream_error_type": self._cluster_type(clusters, c1),
                "downstream_error_type": self._cluster_type(clusters, c2),
                "cascade_count": count,
            })

        cluster_root_scores: Dict[int, int] = defaultdict(int)
        for p in pair_details:
            cluster_root_scores[p["upstream_cluster_id"]] += p["cascade_count"]

        root_summary = [
            {
                "cluster_id": cid,
                "error_type": self._cluster_type(clusters, cid),
                "cascade_count": score,
                "is_root": score >= 3,
            }
            for cid, score in sorted(cluster_root_scores.items(), key=lambda x: -x[1])
        ]

        return {
            "cascade_pairs": pair_details[:20],
            "root_clusters": root_summary[:10],
        }

    def _cluster_type(self, clusters: List[Dict[str, Any]], cluster_id: int) -> str:
        for c in clusters:
            if c.get("cluster_id") == cluster_id:
                return c.get("error_type", "Unknown")
        return "Unknown"

    def _compute_co_occurrence(
        self, clusters: List[Dict[str, Any]], events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        event_cluster_map: Dict[str, int] = {}
        for c in clusters:
            for m in c.get("members", []):
                tid = m.get("thread_id") or m.get("alert_id")
                if tid:
                    event_cluster_map[tid] = c["cluster_id"]

        window_seconds = self.cascade_window * 60
        co_occur: Dict[Tuple[int, int], int] = defaultdict(int)

        sorted_events = sorted(
            [e for e in events if e.get("timestamp")],
            key=lambda e: e["timestamp"],
        )

        for i in range(len(sorted_events)):
            e1 = sorted_events[i]
            c1 = event_cluster_map.get(e1.get("thread_id") or e1.get("alert_id"))
            if c1 is None:
                continue
            t1 = e1["timestamp"]

            for j in range(i + 1, len(sorted_events)):
                e2 = sorted_events[j]
                t2 = e2["timestamp"]
                if isinstance(t1, str) and isinstance(t2, str):
                    try:
                        t1_dt = datetime.fromisoformat(t1)
                        t2_dt = datetime.fromisoformat(t2)
                    except Exception:
                        continue
                else:
                    continue

                diff = (t2_dt - t1_dt).total_seconds()
                if diff > window_seconds:
                    break

                c2 = event_cluster_map.get(e2.get("thread_id") or e2.get("alert_id"))
                if c2 is None or c1 == c2:
                    continue
                pair = (min(c1, c2), max(c1, c2))
                co_occur[pair] += 1

        pairs = [
            {
                "cluster_a": a,
                "cluster_b": b,
                "co_occurrence_count": count,
                "type_a": self._cluster_type(clusters, a),
                "type_b": self._cluster_type(clusters, b),
            }
            for (a, b), count in sorted(co_occur.items(), key=lambda x: -x[1])
            if count >= 2
        ]

        return {"co_occurrence_pairs": pairs[:20]}

    def _compute_hourly_heatmap(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        hourly: Dict[str, int] = defaultdict(int)
        for e in events:
            ts = e.get("timestamp")
            if ts and isinstance(ts, str):
                try:
                    hour_key = ts[:13]
                    hourly[hour_key] += 1
                except Exception:
                    continue

        if not hourly:
            return []

        sorted_hours = sorted(hourly.keys())
        return [
            {"hour": h, "count": hourly[h]} for h in sorted_hours
        ]

    def _compute_service_matrix(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        matrix: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

        for c in clusters:
            for m in c.get("members", []):
                svc = m.get("service_name", "unknown")
                cid = c["cluster_id"]
                matrix[svc][cid] += 1

        result = []
        for svc, cluster_counts in sorted(matrix.items()):
            top_clusters = sorted(cluster_counts.items(), key=lambda x: -x[1])[:5]
            result.append({
                "service": svc,
                "total_events": sum(cluster_counts.values()),
                "cluster_count": len(cluster_counts),
                "top_clusters": [
                    {"cluster_id": cid, "count": cnt}
                    for cid, cnt in top_clusters
                ],
            })

        return sorted(result, key=lambda x: -x["total_events"])
