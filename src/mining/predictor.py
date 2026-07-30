import logging
from typing import List, Dict, Any, Optional
from src.mining.cluster_engine import _significant_tokens, token_tfidf_similarity, _extract_error_type

logger = logging.getLogger(__name__)

DEFAULT_RUNBOOKS: Dict[str, str] = {
    "Connection/Timeout": (
        "1. Check DB connection pool (max_connections, idle_in_transaction_session_timeout)\n"
        "2. Verify network latency between app and DB (<5ms expected)\n"
        "3. Review PgBouncer/pgpool config if present\n"
        "4. Check for long-running queries blocking the pool\n"
        "5. Increase pool size or add read replicas if sustained"
    ),
    "Connection Refused": (
        "1. Verify DB service is running: `systemctl status postgresql`\n"
        "2. Check port availability: `ss -tlnp | grep 5432`\n"
        "3. Review pg_hba.conf for client authentication\n"
        "4. Ensure firewall allows traffic on port 5432\n"
        "5. Check if max_connections limit is reached"
    ),
    "Authentication/Authorization": (
        "1. Check if credentials were recently rotated\n"
        "2. Verify service account permissions in IAM/AD\n"
        "3. Review recent changes to auth provider config\n"
        "4. Check token expiry — are service accounts using long-lived tokens?\n"
        "5. Validate API key format and allowed IP ranges"
    ),
    "Not Found": (
        "1. Check if service was recently redeployed (endpoint removed?)\n"
        "2. Verify DNS records for the target service\n"
        "3. Check service discovery registry (Consul/K8s)\n"
        "4. Review recent config changes for URL/endpoint paths\n"
        "5. Validate that all downstream dependencies are healthy"
    ),
    "Memory": (
        "1. Take a heap dump for analysis\n"
        "2. Check for memory leak pattern in recent deployments\n"
        "3. Review JVM/container memory limits (Xmx, k8s resource limits)\n"
        "4. Verify garbage collection logs for frequency\n"
        "5. Consider memory profiling with async-profiler"
    ),
    "Null Reference": (
        "1. Check if a new code path was introduced without null guard\n"
        "2. Review input validation for the failing endpoint\n"
        "3. Verify that all optional dependencies are properly initialized\n"
        "4. Check if the error correlates with specific input payloads\n"
        "5. Enable nullable reference types or add @Nonnull annotations"
    ),
    "DNS": (
        "1. Check DNS resolver health: `dig @8.8.8.8 <fqdn>`\n"
        "2. Verify /etc/resolv.conf has valid nameservers\n"
        "3. Check DNS cache TTL — too short causes lookup storms\n"
        "4. Ensure external DNS (Route53/CloudDNS) has correct A records\n"
        "5. Consider adding retry logic with exponential backoff"
    ),
    "Storage": (
        "1. Check disk usage: `df -h` across all volumes\n"
        "2. Review log rotation policy — are logs filling the disk?\n"
        "3. Check inode usage: `df -i`\n"
        "4. Verify temp directory cleanup (Java temp, /tmp)\n"
        "5. Consider adding disk alert threshold at 80%"
    ),
    "CPU/Throttling": (
        "1. Check CPU metrics in Grafana for the affected service\n"
        "2. Review recent deployment for CPU-intensive changes\n"
        "3. Check if the pod/container has CPU limits set too low\n"
        "4. Look for infinite loops or runaway goroutines/threads\n"
        "5. Consider HPA scaling thresholds or increasing CPU limits"
    ),
    "SSL/TLS": (
        "1. Check certificate expiry dates\n"
        "2. Verify the CA chain is complete\n"
        "3. Ensure SNI is configured correctly\n"
        "4. Check if the certificate matches the requested hostname\n"
        "5. Test SSL: `openssl s_client -connect <host>:443 -servername <host>`"
    ),
}


class RunbookMatcher:
    def __init__(self, custom_runbooks: Optional[Dict[str, str]] = None):
        self._runbooks = dict(DEFAULT_RUNBOOKS)
        if custom_runbooks:
            self._runbooks.update(custom_runbooks)

    def suggest(self, error_message: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not error_message:
            return []

        novel_tokens = _significant_tokens(error_message)
        fallback_type = _extract_error_type(error_message)

        exact_runbook = self._runbooks.get(fallback_type)
        if exact_runbook and not novel_tokens:
            return [{"error_type": fallback_type, "similarity": 1.0, "runbook": exact_runbook}]

        if not novel_tokens:
            return [{"error_type": "general", "similarity": 0.0, "runbook": ""}]

        scores = []
        for error_type, runbook in self._runbooks.items():
            type_tokens = _significant_tokens(error_type)
            sim = token_tfidf_similarity(novel_tokens, type_tokens)
            if sim > 0.01:
                scores.append((sim, error_type, runbook))

        if fallback_type in self._runbooks and not any(s[1] == fallback_type for s in scores):
            scores.append((0.5, fallback_type, self._runbooks[fallback_type]))

        scores.sort(key=lambda x: -x[0])
        return [
            {"error_type": et, "similarity": round(s, 3), "runbook": rb}
            for s, et, rb in scores[:top_k]
        ]

    def get_runbook(self, error_type: str) -> Optional[str]:
        return self._runbooks.get(error_type)

    def add_runbook(self, error_type: str, runbook_text: str):
        self._runbooks[error_type] = runbook_text

    def list_runbooks(self) -> Dict[str, str]:
        return dict(self._runbooks)
