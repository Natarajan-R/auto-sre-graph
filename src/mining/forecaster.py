import logging
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _validate_series(values: List[float]) -> List[float]:
    if not values:
        return [0.0]
    cleaned = [v if v is not None else 0.0 for v in values]
    if all(v == 0.0 for v in cleaned):
        return cleaned
    return cleaned


class ExponentialSmoother:
    def __init__(self, alpha: float = 0.3):
        self.alpha = max(0.01, min(0.99, alpha))

    def fit_predict(self, values: List[float], steps: int = 24) -> List[float]:
        values = _validate_series(values)
        if len(values) < 2:
            return [values[0]] * steps

        level = values[0]
        for v in values[1:]:
            level = self.alpha * v + (1 - self.alpha) * level

        return [level] * steps


class DoubleExponentialSmoother:
    def __init__(self, alpha: float = 0.3, beta: float = 0.1):
        self.alpha = max(0.01, min(0.99, alpha))
        self.beta = max(0.01, min(0.99, beta))

    def fit_predict(self, values: List[float], steps: int = 24) -> List[float]:
        values = _validate_series(values)
        if len(values) < 2:
            return [values[0]] * steps

        level = values[0]
        trend = values[1] - values[0] if len(values) > 1 else 0.0

        for v in values[1:]:
            prev_level = level
            level = self.alpha * v + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - prev_level) + (1 - self.beta) * trend

        result = []
        for i in range(1, steps + 1):
            result.append(level + i * trend)
        return [max(0.0, r) for r in result]


def compute_moving_average(values: List[float], window: int = 3) -> List[float]:
    values = _validate_series(values)
    if len(values) < window:
        return [sum(values) / len(values)] * len(values)
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        segment = values[start:i + 1]
        result.append(sum(segment) / len(segment))
    return result


def forecast_cluster(
    cluster_history: List[Dict[str, Any]],
    steps: int = 24,
    method: str = "double_exp",
) -> Dict[str, Any]:
    if not cluster_history:
        return {
            "forecast": [0.0] * steps,
            "peak": 0.0,
            "avg": 0.0,
            "trend_direction": "unknown",
        }

    values = [float(c.get("size", 0)) for c in cluster_history]
    values.reverse()

    if method == "double_exp":
        smoother = DoubleExponentialSmoother(alpha=0.3, beta=0.1)
    else:
        smoother = ExponentialSmoother(alpha=0.3)

    forecast = smoother.fit_predict(values, steps)

    last_value = values[-1] if values else 0.0
    peak = max(forecast)
    avg = sum(forecast) / len(forecast) if forecast else 0.0

    direction = "stable"
    if len(values) >= 3:
        recent_avg = sum(values[-3:]) / 3
        forecast_avg = sum(forecast[:8]) / 8 if len(forecast) >= 8 else sum(forecast) / len(forecast)
        if forecast_avg > recent_avg * 1.2:
            direction = "rising"
        elif forecast_avg < recent_avg * 0.8:
            direction = "falling"

    return {
        "forecast": [round(f, 2) for f in forecast],
        "peak": round(peak, 2),
        "avg": round(avg, 2),
        "last_observed": round(last_value, 2),
        "trend_direction": direction,
    }


def compute_page_risk_score(
    cluster: Dict[str, Any],
    forecast: Dict[str, Any],
    cascade_count: int = 0,
) -> float:
    velocity = abs(cluster.get("velocity", 0.0))
    trend = cluster.get("trend", "stable")

    score = 0.0

    if trend == "accelerating":
        score += 0.25 * min(velocity / 5.0, 1.0)

    current_size = float(cluster.get("size", 0))
    score += 0.25 * min(current_size / 50.0, 1.0)

    forecast_peak = forecast.get("peak", 0.0)
    if forecast_peak > current_size * 1.3 and current_size > 0:
        score += 0.2

    if cascade_count >= 3:
        score += 0.15 * min(cascade_count / 10.0, 1.0)

    if not cluster.get("is_noise", True):
        score += 0.15
    else:
        score += 0.05

    return min(round(score, 4), 1.0)


def rank_clusters_by_risk(
    clusters: List[Dict[str, Any]],
    history_map: Dict[int, List[Dict[str, Any]]],
    cascade_map: Optional[Dict[int, int]] = None,
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    cascade_map = cascade_map or {}

    scored = []
    for c in clusters:
        cid = c.get("cluster_id", -1)
        hist = history_map.get(cid, [])
        fc = forecast_cluster(hist, steps=24)
        cascade_count = cascade_map.get(cid, 0)
        risk = compute_page_risk_score(c, fc, cascade_count)

        scored.append({
            "cluster_id": cid,
            "error_type": c.get("error_type", "Unknown"),
            "current_size": c.get("size", 0),
            "velocity": c.get("velocity", 0.0),
            "trend": c.get("trend", "stable"),
            "forecast_peak": fc.get("peak", 0.0),
            "forecast_avg": fc.get("avg", 0.0),
            "trend_direction": fc.get("trend_direction", "stable"),
            "cascade_count": cascade_count,
            "page_risk_score": risk,
            "page_risk_label": _risk_label(risk),
            "services": c.get("services", []),
        })

    scored.sort(key=lambda x: -x["page_risk_score"])
    return scored[:top_n]


def _risk_label(score: float) -> str:
    if score >= 0.7:
        return "critical"
    if score >= 0.4:
        return "high"
    if score >= 0.2:
        return "medium"
    return "low"
