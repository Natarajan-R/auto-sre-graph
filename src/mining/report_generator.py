import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self):
        self._llm_available = None

    async def generate_report(
        self,
        clusters: List[Dict[str, Any]],
        patterns: Dict[str, Any],
        days: int = 7,
        format: str = "markdown",
    ) -> str:
        rule_based = self._build_rule_based_report(clusters, patterns, days)

        llm_report = await self._try_llm_enhancement(clusters, patterns, days)
        if llm_report:
            return llm_report

        return rule_based

    async def _try_llm_enhancement(
        self,
        clusters: List[Dict[str, Any]],
        patterns: Dict[str, Any],
        days: int,
    ) -> Optional[str]:
        try:
            from src.config.settings import settings

            has_key = (
                settings.OPENAI_API_KEY
                and settings.OPENAI_API_KEY.get_secret_value()
                and settings.OPENAI_API_KEY.get_secret_value() not in ("", "your-openai-api-key")
            )
            if not has_key:
                return None

            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY.get_secret_value())

            top_clusters = clusters[:5]
            velocity = patterns.get("velocity_analysis", [])[:5]
            cascade = patterns.get("cascade_roots", {})
            roots = cascade.get("root_clusters", [])[:5]

            prompt = self._build_llm_prompt(top_clusters, velocity, roots, days)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an SRE reliability analyst. Given error cluster data, "
                            "produce a concise system health report. Use markdown. "
                            "Focus on: 1) top systemic issues, 2) root causes, "
                            "3) recommended actions, 4) trends to watch."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            llm_text = response.choices[0].message.content
            if llm_text:
                header = (
                    f"# Auto-SRE-Graph System Health Report\n"
                    f"**Period:** Last {days} days  \n"
                    f"**Generated:** {datetime.utcnow().isoformat()}  \n"
                    f"**Method:** AI-Enhanced (GPT-4o-mini)\n\n"
                    f"---\n\n"
                )
                return header + llm_text

        except ImportError:
            logger.info("OpenAI SDK not available for LLM report enhancement")
        except Exception as e:
            logger.warning(f"LLM report enhancement failed: {e}")

        return None

    def _build_llm_prompt(
        self,
        top_clusters: List[Dict[str, Any]],
        velocity: List[Dict[str, Any]],
        cascade_roots: List[Dict[str, Any]],
        days: int,
    ) -> str:
        lines = [f"Analysis period: last {days} days\n"]

        lines.append("=== TOP ERROR CLUSTERS ===")
        for c in top_clusters:
            lines.append(
                f"- Cluster {c.get('cluster_id')}: {c.get('error_type', 'Unknown')} "
                f"({c.get('size', 0)} occurrences, services: {c.get('services', [])})"
            )
            lines.append(f"  Example: {c.get('representative_error', '')[:150]}")

        lines.append("\n=== VELOCITY TRENDS ===")
        for v in velocity:
            icon = "⚠️" if v.get("trend") == "accelerating" else "✅" if v.get("trend") == "declining" else "➡️"
            lines.append(
                f"- {icon} {v.get('error_type')}: {v.get('trend')} "
                f"(velocity={v.get('velocity', 0)}, avg {v.get('avg_daily', 0)}/day)"
            )

        lines.append("\n=== CASCADE ROOTS ===")
        for r in cascade_roots:
            lines.append(
                f"- Cluster {r.get('cluster_id')} ({r.get('error_type')}): "
                f"appears first in {r.get('cascade_count', 0)} cascades"
            )

        lines.append(
            "\n\nPlease provide: \n"
            "1. Executive summary of system health\n"
            "2. Top 3 systemic issues (patterns that need attention)\n"
            "3. Root cause analysis of cascading failures\n"
            "4. Recommended actions prioritized by impact\n"
            "5. Things to watch in the coming week"
        )

        return "\n".join(lines)

    def _build_rule_based_report(
        self,
        clusters: List[Dict[str, Any]],
        patterns: Dict[str, Any],
        days: int,
    ) -> str:
        lines = []
        lines.append(f"# Auto-SRE-Graph System Health Report")
        lines.append(f"**Period:** Last {days} days")
        lines.append(f"**Generated:** {datetime.utcnow().isoformat()}")
        lines.append(f"**Method:** Rule-Based Analysis")
        lines.append("")
        lines.append("---")
        lines.append("")

        total_events = sum(c.get("size", 0) for c in clusters)
        noise_events = sum(c.get("size", 0) for c in clusters if c.get("is_noise"))
        real_clusters = [c for c in clusters if not c.get("is_noise")]

        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"- **Total error events:** {total_events}")
        lines.append(f"- **Pattern families found:** {len(real_clusters)}")
        lines.append(f"- **Noise/unique errors:** {noise_events} ({self._pct(noise_events, total_events)}%)")
        lines.append(f"- **Top error type:** {real_clusters[0].get('error_type', 'N/A') if real_clusters else 'N/A'}")
        lines.append("")

        velocity_data = patterns.get("velocity_analysis", [])
        accelerating = [v for v in velocity_data if v.get("trend") == "accelerating"]
        if accelerating:
            lines.append(f"- **⚠ Accelerating errors:** {len(accelerating)} patterns getting worse")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Top Systemic Issues")
        lines.append("")

        for i, c in enumerate(real_clusters[:5]):
            rank = i + 1
            pct = self._pct(c.get("size", 0), total_events)
            services = ", ".join(c.get("services", []))
            lines.append(f"### {rank}. {c.get('error_type', 'Unknown')} ({c.get('size', 0)} events, {pct}%)")
            lines.append("")
            lines.append(f"- **Example:** `{c.get('representative_error', '')[:200]}`")
            lines.append(f"- **Affected services:** {services}")
            lines.append(f"- **First seen:** {c.get('first_seen', 'N/A')}")
            lines.append(f"- **Last seen:** {c.get('last_seen', 'N/A')}")

            for v in velocity_data:
                if v.get("cluster_id") == c.get("cluster_id"):
                    lines.append(f"- **Trend:** {v.get('trend')} (velocity={v.get('velocity')}, avg {v.get('avg_daily')}/day)")
            lines.append("")

        cascade = patterns.get("cascade_roots", {})
        roots = cascade.get("root_clusters", [])
        if roots:
            lines.append("---")
            lines.append("")
            lines.append("## Cascade Root Analysis")
            lines.append("")
            lines.append("Errors that consistently appear FIRST in failure cascades:")
            lines.append("")
            for r in roots[:5]:
                lines.append(f"- **Cluster {r.get('cluster_id')} ({r.get('error_type')})**: "
                             f"root in {r.get('cascade_count', 0)} cascades")
            lines.append("")

        co_occur = patterns.get("co_occurrence", {})
        pairs = co_occur.get("co_occurrence_pairs", [])
        if pairs:
            lines.append("---")
            lines.append("")
            lines.append("## Co-Occurrence Patterns")
            lines.append("")
            lines.append("Errors that frequently happen together:")
            lines.append("")
            for p in pairs[:5]:
                lines.append(f"- **{p.get('type_a')}** ↔ **{p.get('type_b')}** "
                             f"(appeared together {p.get('co_occurrence_count')} times)")
            lines.append("")

        svc_matrix = patterns.get("service_cluster_matrix", [])
        if svc_matrix:
            lines.append("---")
            lines.append("")
            lines.append("## Service Impact Summary")
            lines.append("")
            lines.append("| Service | Events | Top Error Cluster |")
            lines.append("|---------|--------|-------------------|")
            for s in svc_matrix[:10]:
                top = s.get("top_clusters", [{}])[0] if s.get("top_clusters") else {}
                top_type = "—"
                for c in real_clusters:
                    if c.get("cluster_id") == top.get("cluster_id"):
                        top_type = c.get("error_type", "—")
                        break
                lines.append(f"| {s.get('service', 'unknown')} | {s.get('total_events', 0)} | {top_type} |")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")

        if real_clusters:
            top = real_clusters[0]
            lines.append(f"1. **Investigate {top.get('error_type')}** — highest volume cluster "
                         f"({top.get('size', 0)} events, {self._pct(top.get('size', 0), total_events)}% of all errors)")

        if roots:
            root = roots[0]
            lines.append(f"2. **Fix cascade root** — Cluster {root.get('cluster_id')} ({root.get('error_type')}) "
                         f"appears first in failure cascades. Addressing this may eliminate downstream alerts.")

        if accelerating:
            for v in accelerating[:2]:
                lines.append(f"3. **Watch accelerating trend** — {v.get('error_type')} is "
                             f"increasing (velocity={v.get('velocity')})")

        lines.append("4. **Review novel errors** — check unique errors for zero-day issues")
        lines.append("")

        return "\n".join(lines)

    def _pct(self, part: int, total: int) -> str:
        if total == 0:
            return "0.0"
        return f"{round(part / total * 100, 1)}"
