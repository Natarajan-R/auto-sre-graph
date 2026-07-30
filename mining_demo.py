"""
Pattern Mining Engine — Live Demo

Simulates the complete mining pipeline:
  1. Seed historical error events (simulates tripwire data accumulating)
  2. Run clustering to discover pattern families
  3. Detect temporal trends and cascade roots
  4. Generate a health report

Usage:
  python mining_demo.py                    # full demo with all stages
  python mining_demo.py clusters           # clustering only
  python mining_demo.py patterns           # patterns only
  python mining_demo.py report             # health report only
  python mining_demo.py -h                 # help
"""

import sys
import json
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

SEP = "=" * 78
PAD = "  "

SEED_EVENTS = [
    # Cluster 0: Database connection timeouts
    {"service_name": "payment-service", "error_message": "Connection timeout to database: Connection refused after 30s on endpoint db-primary:5432", "severity": "CRITICAL", "days_ago": 7},
    {"service_name": "payment-service", "error_message": "DB connection timeout: psycopg2.OperationalError connection to server at 10.0.1.50 port 5432 failed", "severity": "CRITICAL", "days_ago": 6},
    {"service_name": "payment-service", "error_message": "Cannot connect to PostgreSQL: timeout waiting for connection from pool after 30000ms", "severity": "HIGH", "days_ago": 6},
    {"service_name": "order-service", "error_message": "database connection timeout - cannot reach db-primary.internal:5432", "severity": "HIGH", "days_ago": 5},
    {"service_name": "payment-service", "error_message": "Connection timeout to database: Connection refused after 30s on endpoint db-primary:5432", "severity": "CRITICAL", "days_ago": 4},
    {"service_name": "payment-service", "error_message": "DB connection timeout: could not connect to database server", "severity": "HIGH", "days_ago": 3},
    {"service_name": "order-service", "error_message": "Connection timeout to database: timeout waiting for connection", "severity": "CRITICAL", "days_ago": 2},
    {"service_name": "payment-service", "error_message": "DB connection timeout: psycopg2.OperationalError connection refused", "severity": "CRITICAL", "days_ago": 1},

    # Cluster 1: Authentication failures
    {"service_name": "auth-service", "error_message": "Authentication failed: invalid credentials for user admin from 10.0.1.100", "severity": "HIGH", "days_ago": 7},
    {"service_name": "auth-service", "error_message": "Authorization denied: token expired for API key sk-live-xxxx", "severity": "MEDIUM", "days_ago": 6},
    {"service_name": "auth-service", "error_message": "Authentication failed: invalid credentials provided for service account", "severity": "HIGH", "days_ago": 5},
    {"service_name": "auth-service", "error_message": "Permission denied: user does not have access to resource payment-api/v2/process", "severity": "MEDIUM", "days_ago": 4},
    {"service_name": "auth-service", "error_message": "Authentication failed: invalid credentials for user admin", "severity": "HIGH", "days_ago": 3},
    {"service_name": "auth-service", "error_message": "Token validation failed: JWT signature invalid", "severity": "HIGH", "days_ago": 2},

    # Cluster 2: DNS resolution failures
    {"service_name": "payment-service", "error_message": "DNS resolution failed for endpoint api.external-processor.com: Name or service not known", "severity": "HIGH", "days_ago": 6},
    {"service_name": "payment-service", "error_message": "DNS resolution failed for api.external-processor.com: Temporary failure in name resolution", "severity": "HIGH", "days_ago": 5},
    {"service_name": "payment-service", "error_message": "DNS resolution failed: cannot resolve host api.external-processor.com", "severity": "HIGH", "days_ago": 3},
    {"service_name": "payment-service", "error_message": "DNS resolution failed for endpoint api.external-processor.com: Name or service not known", "severity": "HIGH", "days_ago": 2},
    {"service_name": "payment-service", "error_message": "DNS resolution failed: getaddrinfo ENOTFOUND api.external-processor.com", "severity": "HIGH", "days_ago": 1},

    # Cluster 3: Memory errors (small cluster — accelerating)
    {"service_name": "payment-service", "error_message": "OutOfMemoryError: Java heap space — unable to allocate 256MB for transaction processing", "severity": "CRITICAL", "days_ago": 5},
    {"service_name": "payment-service", "error_message": "MemoryError: cannot allocate 512MB in worker thread pool-4-thread-12", "severity": "CRITICAL", "days_ago": 3},
    {"service_name": "order-service", "error_message": "OutOfMemoryError: GC overhead limit exceeded in order processing pipeline", "severity": "CRITICAL", "days_ago": 2},
    {"service_name": "payment-service", "error_message": "MemoryError: unable to allocate 1GB for batch processing job", "severity": "CRITICAL", "days_ago": 1},

    # Cluster 4: HTTP 503 / upstream failures (cascading from DB issues)
    {"service_name": "payment-service", "error_message": "HTTP 503 Service Unavailable: upstream payment-processor:8080 not reachable", "severity": "HIGH", "days_ago": 6},
    {"service_name": "order-service", "error_message": "HTTP 503 from payment-api: upstream connection refused", "severity": "HIGH", "days_ago": 5},
    {"service_name": "payment-service", "error_message": "HTTP 503: service unavailable — upstream timeout after 30s", "severity": "HIGH", "days_ago": 4},
    {"service_name": "order-service", "error_message": "HTTP 503 from payment-api: upstream connection refused — circuit breaker open", "severity": "HIGH", "days_ago": 3},
    {"service_name": "payment-service", "error_message": "HTTP 503 Service Unavailable: upstream payment-processor:8080 not reachable", "severity": "HIGH", "days_ago": 2},

    # Noise events (unique, no cluster)
    {"service_name": "logging-service", "error_message": "Certificate expiration warning: TLS cert for *.example.com expires in 14 days", "severity": "LOW", "days_ago": 4},
    {"service_name": "user-service", "error_message": "Disk space warning: 85% on /var/log volume", "severity": "LOW", "days_ago": 3},
    {"service_name": "notification-service", "error_message": "Rate limit exceeded: 100 requests per minute for endpoint /api/send", "severity": "LOW", "days_ago": 1},
]


def generate_events():
    now = datetime.utcnow()
    events = []
    for i, seed in enumerate(SEED_EVENTS):
        ts = now - timedelta(days=seed["days_ago"], hours=hash(str(i)) % 24, minutes=hash(str(i * 7)) % 60)
        events.append({
            "thread_id": f"MINING-DEMO-{i:04d}",
            "alert_id": f"MINING-DEMO-{i:04d}",
            "timestamp": ts.isoformat(),
            "service_name": seed["service_name"],
            "error_message": seed["error_message"],
            "severity": seed["severity"],
            "environment": "PROD",
            "stack_trace": "",
            "final_status": "COMPLETED",
        })
    return events


def print_header(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(f"{SEP}\n")


def print_json(label, data):
    print(f"{PAD}{label}:")
    printed = json.dumps(data, indent=2, default=str)
    for line in printed.split("\n"):
        print(f"{PAD}  {line}")
    print()


async def demo_clusters(events):
    from src.mining.cluster_engine import ClusterEngine

    print_header("STAGE 1: Error Clustering — Discovering Pattern Families")

    clusterer = ClusterEngine(similarity_threshold=0.35)
    clusters = clusterer.cluster_events(events)

    total = len(events)
    real = [c for c in clusters if not c["is_noise"]]
    noise = [c for c in clusters if c["is_noise"]]
    noise_count = sum(c["size"] for c in noise)

    print(f"{PAD}Total events: {total}")
    print(f"{PAD}Pattern families: {len(real)}")
    print(f"{PAD}Noise (unique events): {noise_count}\n")

    for i, c in enumerate(real[:5]):
        pct = round(c["size"] / total * 100, 1) if total else 0
        services = ", ".join(c["services"])
        print(f"{PAD}  Cluster {i+1}: {c['error_type']} — {c['size']} events ({pct}%)")
        print(f"{PAD}    Services: {services}")
        print(f"{PAD}    Example: {c['representative_error'][:120]}...")

    print()
    return clusters


async def demo_patterns(events, clusters):
    from src.mining.pattern_detector import PatternDetector

    print_header("STAGE 2: Pattern Detection — Velocity & Cascade Analysis")

    detector = PatternDetector(cascade_window_minutes=5)
    patterns = detector.analyze_clusters(clusters, events)

    velocity = patterns.get("velocity_analysis", [])
    print(f"{PAD}Velocity Analysis:")
    for v in velocity[:5]:
        icon = {"accelerating": "⚠", "declining": "✅", "stable": "➡"}.get(v["trend"], "➡")
        print(f"{PAD}  {icon} {v['error_type']}: {v['trend']} (vel={v['velocity']}, avg={v['avg_daily']}/d)")

    cascade = patterns.get("cascade_roots", {})
    roots = cascade.get("root_clusters", [])
    if roots:
        print(f"\n{PAD}Cascade Roots (errors that appear first in chains):")
        for r in roots[:5]:
            print(f"{PAD}  🔴 Cluster {r['cluster_id']} ({r['error_type']}): "
                  f"root in {r['cascade_count']} cascades")

    co = patterns.get("co_occurrence", {})
    pairs = co.get("co_occurrence_pairs", [])
    if pairs:
        print(f"\n{PAD}Co-Occurrence Patterns:")
        for p in pairs[:3]:
            print(f"{PAD}  🔗 {p['type_a']} ↔ {p['type_b']} ({p['co_occurrence_count']}×)")

    print()
    return patterns


async def demo_report(events, clusters, patterns):
    from src.mining.report_generator import ReportGenerator

    print_header("STAGE 3: System Health Report")

    gen = ReportGenerator()
    report = await gen.generate_report(clusters, patterns, days=7)

    for line in report.split("\n"):
        print(f"{PAD}  {line}")

    print()


async def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: python mining_demo.py [stage]")
        print()
        print("Stages:")
        print("  clusters    — Error clustering only")
        print("  patterns    — Pattern detection only")
        print("  report      — Health report only")
        print("  (all)       — Full pipeline")
        sys.exit(0)

    print()
    print("╔" + "═" * 76 + "╗")
    print("║" + "  Pattern Mining Engine — Live Demo".center(74) + "║")
    print("╚" + "═" * 76 + "╝")

    events = generate_events()

    stages = args if args else ["clusters", "patterns", "report"]

    clusters = None
    patterns = None

    for stage in stages:
        if stage == "clusters":
            clusters = await demo_clusters(events)
        elif stage == "patterns":
            if clusters is None:
                clusters = await demo_clusters(events)
            patterns = await demo_patterns(events, clusters)
        elif stage == "report":
            if clusters is None:
                clusters = await demo_clusters(events)
            if patterns is None:
                from src.mining.pattern_detector import PatternDetector
                detector = PatternDetector()
                patterns = detector.analyze_clusters(clusters, events)
            await demo_report(events, clusters, patterns)
        else:
            print(f"  Unknown stage: {stage}")

    print(f"\n{SEP}")
    print("  Mining demo complete.")
    print(f"{SEP}\n")


if __name__ == "__main__":
    asyncio.run(main())
