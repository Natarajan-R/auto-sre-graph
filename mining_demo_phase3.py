"""
Pattern Mining Engine — Phase 3 Predictive Demo

Demonstrates the three Phase 3 features:
  1. Time-series forecasting (exponential smoothing) for each cluster
  2. "Likely to page in next 24h" risk ranking
  3. Automated runbook suggestions for novel errors

Data convention: cluster histories are stored newest-first (matching the
persist layer's ORDER BY snapshot_start DESC).  forecast_cluster() reverses
to chronological order internally before fitting.

Usage:
  python mining_demo_phase3.py
  python mining_demo_phase3.py forecast      # forecasting only
  python mining_demo_phase3.py risk          # page risk scoring only
  python mining_demo_phase3.py runbook       # runbook suggestion only
  python mining_demo_phase3.py -h            # help
"""

import sys
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from src.mining.forecaster import (
    ExponentialSmoother,
    DoubleExponentialSmoother,
    compute_moving_average,
    forecast_cluster,
    compute_page_risk_score,
    rank_clusters_by_risk,
)
from src.mining.predictor import RunbookMatcher

_UTC = timezone.utc
SEP = "=" * 78
PAD = "  "


# ---------------------------------------------------------------------------
# Sample data — stored newest-first (as the persist layer provides).
# After internal reversal, chronology becomes oldest-first for the model.
# ---------------------------------------------------------------------------

# Connection/Timeout: grew from 5 → 58 over 10 snapshots — accelerating
#   newest-first:  [58, 50, 42, 35, 28, 22, 15, 12,  8,  5]
#   after reverse: [ 5,  8, 12, 15, 22, 28, 35, 42, 50, 58]  → rising
CONN_HISTORY = [58, 50, 42, 35, 28, 22, 15, 12, 8, 5]

# Auth: stable around 5-12 — no strong trend
#   newest-first:  [ 5,  6,  7,  8,  9, 10, 12, 11, 10, 12]
#   after reverse: [12, 10, 11, 12, 10,  9,  8,  7,  6,  5]  → slightly declining
AUTH_HISTORY = [5, 6, 7, 8, 9, 10, 12, 11, 10, 12]

# DNS: declining from 7 → 1
#   newest-first:  [ 1,  2,  3,  4,  5,  6,  7,  5,  4,  3]
#   after reverse: [ 3,  4,  5,  7,  6,  5,  4,  3,  2,  1]  → declining
DNS_HISTORY = [1, 2, 3, 4, 5, 6, 7, 5, 4, 3]

# Memory: newly emerging (0 → 11 over last 4 snapshots)
#   newest-first:  [11,  7,  4,  2,  1,  0,  0,  0,  0,  0]
#   after reverse: [ 0,  0,  0,  0,  0,  1,  2,  4,  7, 11]  → rapidly rising
MEM_HISTORY = [11, 7, 4, 2, 1, 0, 0, 0, 0, 0]

SAMPLE_HISTORY = {
    "Connection/Timeout": CONN_HISTORY,
    "Authentication/Authorization": AUTH_HISTORY,
    "DNS": DNS_HISTORY,
    "Memory": MEM_HISTORY,
}

SAMPLE_CLUSTERS = [
    {"cluster_id": 0, "error_type": "Connection/Timeout", "size": 58, "velocity": 4.5,
     "trend": "accelerating", "is_noise": False, "services": ["payment", "order"]},
    {"cluster_id": 1, "error_type": "Authentication/Authorization", "size": 5, "velocity": -0.8,
     "trend": "declining", "is_noise": False, "services": ["auth"]},
    {"cluster_id": 2, "error_type": "DNS", "size": 1, "velocity": -2.0,
     "trend": "declining", "is_noise": False, "services": ["payment"]},
    {"cluster_id": 3, "error_type": "Memory", "size": 11, "velocity": 3.2,
     "trend": "accelerating", "is_noise": False, "services": ["order", "payment"]},
]

CASCADE_MAP = {0: 12, 1: 2, 2: 0, 3: 4}

NOVEL_ERRORS = [
    "Connection timeout to database: refused after 30s on endpoint db-primary:5432",
    "Authentication failed: invalid credentials for service account admin",
    "OutOfMemoryError: Java heap space - unable to allocate 512MB",
    "SSL certificate verification failed: certificate has expired for api.payments.com",
    "xylophone driver not initialized in hypervisor mode",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chrono_label(etype: str) -> str:
    """Show the chronological (oldest-first) values that the model sees."""
    raw = list(SAMPLE_HISTORY[etype])
    raw.reverse()
    return " → ".join(str(v) for v in raw)


# ---------------------------------------------------------------------------
# Demo stages
# ---------------------------------------------------------------------------

async def demo_forecasting():
    print(f"\n{SEP}")
    print("  STAGE 1: Time-Series Forecasting")
    print(f"{SEP}\n")

    print(f"  Models: SES (Simple Exponential Smoothing, flat forecast)")
    print(f"          DES (Double Exponential Smoothing, trend-aware)")
    print()
    print(f"  Data format: newest-first snapshots → reversed to chronological")
    print(f"  before fitting.  Forecast: next 24 hours (8 steps shown).\n")

    for error_type, raw_values in SAMPLE_HISTORY.items():
        history = [{"size": v} for v in raw_values]
        chrono = _chrono_label(error_type)
        newest = raw_values[0]

        simple_fc = forecast_cluster(history, steps=8, method="simple")
        double_fc = forecast_cluster(history, steps=8, method="double_exp")

        simple_avg = simple_fc["avg"]
        double_avg = double_fc["avg"]
        double_peak = double_fc["peak"]
        double_dir = double_fc["trend_direction"]

        print(f"  {error_type:35s}")
        print(f"    Newest-first:           {raw_values}")
        print(f"    Chronological (model):  [{chrono}]")
        print(f"    Latest value:           {newest}")
        print(f"    SES forecast avg:       {simple_avg:>6.1f}")
        print(f"    DES forecast avg:       {double_avg:>6.1f}  "
              f"peak={double_peak:>6.1f}  direction={double_dir}")
        print()

    print(f"  Interpretation:\n")
    print(f"    Connection/Timeout  — Chronological values grow 5→58  → DES forecasts rising  │  ⚠  accelerating")
    print(f"    Memory              — Newly emerged (0→11 in 4 steps) → DES forecasts rising  │  ⚠  watch closely")
    print(f"    Auth                — Stable around 5-12              → SES/DES ≈ flat        │  ➡  chronic")
    print(f"    DNS                 — Declining from 7→1              → DES forecasts falling │  ✅  resolving")
    print()


async def demo_risk_ranking():
    print(f"\n{SEP}")
    print('  STAGE 2: Page Risk Scoring ("Likely to page in next 24h")')
    print(f"{SEP}\n")

    print(f"  Risk components:  velocity + cluster size + forecast peak + cascade count\n")

    history_map = {}
    for c in SAMPLE_CLUSTERS:
        cid = c["cluster_id"]
        raw = SAMPLE_HISTORY[c["error_type"]]
        history_map[cid] = [{"size": v} for v in raw]

    ranked = rank_clusters_by_risk(
        SAMPLE_CLUSTERS, history_map, cascade_map=CASCADE_MAP, top_n=10
    )

    hdr = f"{PAD}{'Rank':5s} {'ID':4s} {'Error Type':30s} {'Score':8s} {'Label':10s} {'Trend':12s} {'Velo':6s} {'Forecast Pk':10s} {'Cascade':8s}"
    print(hdr)
    print(f"{PAD}{'─'*len(hdr)}")

    for i, r in enumerate(ranked):
        print(f"{PAD}{i+1:3d}.   #{r['cluster_id']:<3d} {r['error_type']:30s} "
              f"{r['page_risk_score']:.3f}   {r['page_risk_label']:10s} "
              f"{r['trend']:12s} {r['velocity']:+0.1f}  "
              f"{r['forecast_peak']:>6.1f}      {r['cascade_count']}")
    print()

    print(f"  Top risks:\n")
    for r in ranked[:3]:
        icon = "🔴" if r["page_risk_label"] == "critical" else "🟡"
        print(f"  {icon}  #{r['cluster_id']} {r['error_type']:30s}  "
              f"{r['page_risk_label']:>8s} ({r['page_risk_score']:.0%})  "
              f"size={r['current_size']}→{r['forecast_peak']:.0f}  "
              f"velo={r['velocity']:+0.1f}")
    print()


async def demo_runbook_matching():
    print(f"\n{SEP}")
    print("  STAGE 3: Automated Runbook Suggestions")
    print(f"{SEP}\n")

    matcher = RunbookMatcher()
    print(f"  Available runbooks: {len(matcher.list_runbooks())}\n")

    for error in NOVEL_ERRORS:
        suggestions = matcher.suggest(error, top_k=2)
        print(f"  Error: {error[:80]}")
        if suggestions:
            for s in suggestions:
                first_step = s["runbook"].split("\n")[0].strip()
                print(f"    → {s['error_type']:35s} sim={s['similarity']:.3f}  |  {first_step}")
        else:
            print(f"    → No matching runbook (unclassified novel error)")
        print()


async def demo_full_pipeline():
    print(f"\n{SEP}")
    print("  BONUS: End-to-End Prediction Pipeline")
    print(f"{SEP}\n")

    history_map = {}
    for c in SAMPLE_CLUSTERS:
        cid = c["cluster_id"]
        raw = SAMPLE_HISTORY[c["error_type"]]
        history_map[cid] = [{"size": v} for v in raw]

    # Step 1
    print("  Step 1 / 3 — Forecast each cluster")
    for c in SAMPLE_CLUSTERS:
        fc = forecast_cluster(history_map[c["cluster_id"]], steps=24)
        print(f"    #{c['cluster_id']} {c['error_type']:35s} "
              f"→ 24h peak={fc['peak']:>6.1f}  direction={fc['trend_direction']}")
    print()

    # Step 2
    print("  Step 2 / 3 — Compute page risk scores")
    ranked = rank_clusters_by_risk(SAMPLE_CLUSTERS, history_map, cascade_map=CASCADE_MAP)
    for r in ranked:
        icon = "🔴" if r["page_risk_label"] == "critical" else "🟡" if r["page_risk_label"] == "high" else "🟢"
        print(f"    {icon} #{r['cluster_id']} {r['error_type']:35s} "
              f"risk={r['page_risk_score']:.2f}  ({r['page_risk_label']})")
    print()

    # Step 3
    print("  Step 3 / 3 — Suggest runbook for the top risk cluster")
    top = ranked[0]
    novel = NOVEL_ERRORS[0]
    suggestions = RunbookMatcher().suggest(novel, top_k=1)
    print(f"    Top risk cluster: #{top['cluster_id']} {top['error_type']}")
    print(f"    Novel error:      {novel[:70]}...")
    if suggestions:
        s = suggestions[0]
        first_step = s["runbook"].split("\n")[0].strip()
        print(f"    Suggested:        {s['error_type']} (sim={s['similarity']:.3f})")
        print(f"    First step:       {first_step}")
    print()
    print("  Pipeline complete: forecast → risk score → runbook match\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    stages = {
        "forecast": demo_forecasting,
        "risk": demo_risk_ranking,
        "runbook": demo_runbook_matching,
        "pipeline": demo_full_pipeline,
    }

    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return

    selected = [a for a in sys.argv[1:] if a in stages]

    if not selected:
        await demo_forecasting()
        await demo_risk_ranking()
        await demo_runbook_matching()
        await demo_full_pipeline()
        print(f"{SEP}\n  Phase 3 demo complete.\n")
    else:
        for name in selected:
            await stages[name]()


if __name__ == "__main__":
    asyncio.run(main())
