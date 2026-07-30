import logging
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Body
from src.mining.event_store import MiningEventStore
from src.mining.cluster_engine import ClusterEngine, EmbeddingClusterEngine
from src.mining.pattern_detector import PatternDetector
from src.mining.report_generator import ReportGenerator
from src.mining.persist import MiningPersist
from src.mining.scheduler import MiningScheduler
from src.mining.notifier import MiningNotifier
from src.mining.forecaster import forecast_cluster, rank_clusters_by_risk
from src.mining.predictor import RunbookMatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mining", tags=["mining"])

event_store = MiningEventStore()
text_clusterer = ClusterEngine(similarity_threshold=0.35)
embedding_clusterer = EmbeddingClusterEngine(similarity_threshold=0.75)
pattern_detector = PatternDetector(cascade_window_minutes=5)
report_gen = ReportGenerator()
persist = MiningPersist()
scheduler = MiningScheduler(interval_minutes=60)
notifier = MiningNotifier()
runbook_matcher = RunbookMatcher()

_mining_run_metrics = {
    "clusters_detected": 0,
    "new_clusters": 0,
    "velocity_spikes": 0,
    "runs_completed": 0,
}


async def _run_scheduled_mining():
    days = 7
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    period = end.strftime("%Y%m%d%H")

    logger.info(f"Scheduled mining: fetching events (period={period}, days={days})")
    events = await event_store.get_events(days=days, limit=5000)

    if not events:
        logger.info("Scheduled mining: no events to process")
        return

    clusters = text_clusterer.cluster_events(events)
    patterns = pattern_detector.analyze_clusters(clusters, events)

    persisted = await persist.save_cluster_snapshot(clusters, period, start, end)

    velocity_data = patterns.get("velocity_analysis", [])
    cascade_roots = patterns.get("cascade_roots", {}).get("root_clusters", [])

    previous_period = await persist.get_latest_snapshot_period()
    previous_clusters = []
    if previous_period and previous_period != period:
        previous_clusters = await persist.load_clusters(period=previous_period)

    new_clusters = await notifier.notify_new_clusters(clusters, previous_clusters)
    spikes = await notifier.notify_velocity_spikes(velocity_data)
    roots = await notifier.notify_cascade_root(cascade_roots)

    _mining_run_metrics["clusters_detected"] = len(clusters)
    _mining_run_metrics["new_clusters"] += len(new_clusters)
    _mining_run_metrics["velocity_spikes"] += len(spikes)
    _mining_run_metrics["runs_completed"] += 1

    logger.info(
        f"Scheduled mining complete: {persisted} snapshots, "
        f"{len(new_clusters)} new, {len(spikes)} spikes, {len(roots)} roots"
    )


@router.on_event("startup")
async def start_scheduler():
    scheduler.set_handler(_run_scheduled_mining)
    await scheduler.start()


@router.on_event("shutdown")
async def stop_scheduler():
    await scheduler.stop()


@router.get("/clusters")
async def get_clusters(
    days: int = Query(7, ge=1, le=90),
    min_size: int = Query(1, ge=1),
    service: Optional[str] = Query(None),
    use_embeddings: bool = Query(False),
):
    events = await event_store.get_events(days=days, service=service, limit=5000)

    if use_embeddings:
        clusters = await embedding_clusterer.cluster_events(events)
    else:
        clusters = text_clusterer.cluster_events(events)

    clusters = [c for c in clusters if c["size"] >= min_size]

    return {"total_events": len(events), "cluster_count": len(clusters), "clusters": clusters}


@router.get("/clusters/{cluster_id}/events")
async def get_cluster_events(
    cluster_id: int,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=500),
):
    events = await event_store.get_events(days=days, limit=5000)
    clusters = text_clusterer.cluster_events(events)

    for c in clusters:
        if c["cluster_id"] == cluster_id:
            return {
                "cluster_id": cluster_id,
                "error_type": c.get("error_type"),
                "total_members": c.get("member_count", 0),
                "events": c.get("members", [])[:limit],
            }

    return {"error": f"Cluster {cluster_id} not found"}


@router.get("/patterns")
async def get_patterns(days: int = Query(7, ge=1, le=90)):
    events = await event_store.get_events(days=days, limit=5000)
    clusters = text_clusterer.cluster_events(events)
    patterns = pattern_detector.analyze_clusters(clusters, events)

    return {
        "total_events": len(events),
        "cluster_count": len(clusters),
        "patterns": patterns,
    }


@router.get("/report")
async def get_report(days: int = Query(7, ge=1, le=90), format: str = Query("markdown")):
    events = await event_store.get_events(days=days, limit=5000)
    clusters = text_clusterer.cluster_events(events)
    patterns = pattern_detector.analyze_clusters(clusters, events)
    report = await report_gen.generate_report(clusters, patterns, days=days, format=format)

    return {"report": report}


@router.get("/timeline")
async def get_timeline(
    days: int = Query(7, ge=1, le=90),
    granularity: str = Query("hour", regex="^(hour|day)$"),
):
    timeline = await event_store.get_timeline(days=days, granularity=granularity)
    return {"timeline": timeline}


@router.get("/services")
async def get_service_summary(days: int = Query(7, ge=1, le=90)):
    events = await event_store.get_events(days=days, limit=5000)
    clusters = text_clusterer.cluster_events(events)
    svc_data = pattern_detector._compute_service_matrix(clusters)

    return {"services": svc_data}


@router.get("/metrics")
async def get_mining_metrics():
    m = await persist.get_mining_metrics()
    return {
        "total_snapshots": m.get("total_snapshots", 0),
        "total_clusters": m.get("total_clusters", 0),
        "real_clusters": m.get("real_clusters", 0),
        "accelerating_clusters": m.get("accelerating_clusters", 0),
        "total_events_mined": m.get("total_events", 0),
        "avg_non_stable_velocity": round(float(m.get("avg_non_stable_velocity", 0.0)), 4),
        "scheduler_running": scheduler.running,
        "run_metrics": dict(_mining_run_metrics),
    }


@router.get("/snapshots")
async def get_snapshots(limit: int = Query(20, ge=1, le=100)):
    latest_period = await persist.get_latest_snapshot_period()
    clusters = await persist.load_clusters(limit=limit)
    return {
        "latest_snapshot_period": latest_period,
        "cluster_count": len(clusters),
        "clusters": [
            {
                "cluster_id": c["cluster_id"],
                "error_type": c["error_type"],
                "size": c["size"],
                "trend": c["trend"],
                "velocity": c["velocity"],
                "is_noise": c["is_noise"],
                "snapshot_period": c["snapshot_period"],
            }
            for c in clusters
        ],
    }


@router.post("/run")
async def trigger_mining_run():
    await _run_scheduled_mining()
    return {"status": "mining_run_completed", "timestamp": datetime.utcnow().isoformat()}


@router.get("/predictions")
async def get_predictions(
    hours: int = Query(24, ge=1, le=168),
    min_risk: float = Query(0.0, ge=0.0, le=1.0),
    top_n: int = Query(10, ge=1, le=50),
):
    events = await event_store.get_events(days=7, limit=5000)
    clusters = text_clusterer.cluster_events(events)
    patterns = pattern_detector.analyze_clusters(clusters, events)

    history_map = {}
    for c in clusters:
        cid = c.get("cluster_id", -1)
        members = c.get("members", [])
        daily: Dict[str, int] = {}
        for m in members:
            ts = m.get("timestamp")
            if ts:
                day = ts[:10]
                daily[day] = daily.get(day, 0) + 1
        history_map[cid] = [{"size": v} for v in daily.values()]

    cascade_data = patterns.get("cascade_roots", {}).get("root_clusters", [])
    cascade_map = {r["cluster_id"]: r.get("cascade_count", 0) for r in cascade_data}

    ranked = rank_clusters_by_risk(clusters, history_map, cascade_map, top_n=top_n)
    ranked = [r for r in ranked if r["page_risk_score"] >= min_risk]

    return {
        "forecast_window_hours": hours,
        "total_clusters_analyzed": len(clusters),
        "predictions": ranked,
    }


@router.get("/predictions/{cluster_id}")
async def get_cluster_forecast(
    cluster_id: int,
    days: int = Query(7, ge=1, le=90),
    method: str = Query("double_exp", regex="^(simple|double_exp)$"),
):
    events = await event_store.get_events(days=days, limit=5000)
    clusters = text_clusterer.cluster_events(events)

    target = None
    for c in clusters:
        if c.get("cluster_id") == cluster_id:
            target = c
            break

    if not target:
        return {"error": f"Cluster {cluster_id} not found"}

    members = target.get("members", [])
    daily: Dict[str, int] = {}
    for m in members:
        ts = m.get("timestamp")
        if ts:
            day = ts[:10]
            daily[day] = daily.get(day, 0) + 1

    history = [{"size": v} for v in daily.values()]
    fc = forecast_cluster(history, steps=24, method=method)

    return {
        "cluster_id": cluster_id,
        "error_type": target.get("error_type"),
        "current_size": target.get("size", 0),
        "daily_history": [
            {"date": d, "count": daily[d]}
            for d in sorted(daily.keys())
        ],
        "forecast": fc,
    }


@router.post("/runbook-suggestion")
async def suggest_runbook(
    error_message: str = Body(..., embed=True),
    top_k: int = Query(3, ge=1, le=10),
):
    suggestions = runbook_matcher.suggest(error_message, top_k=top_k)
    return {
        "error_message": error_message[:200],
        "suggestions": suggestions,
    }


@router.get("/runbooks")
async def list_runbooks(error_type: Optional[str] = Query(None)):
    if error_type:
        rb = runbook_matcher.get_runbook(error_type)
        if rb:
            return {"error_type": error_type, "runbook": rb}
        return {"error": f"No runbook for '{error_type}'"}
    return {"runbooks": runbook_matcher.list_runbooks()}
