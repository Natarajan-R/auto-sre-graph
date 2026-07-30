import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp

logger = logging.getLogger(__name__)


class MiningNotifier:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url

    async def notify_new_clusters(
        self,
        clusters: List[Dict[str, Any]],
        previous_snapshot_clusters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        prev_ids = {c.get("cluster_id") for c in previous_snapshot_clusters}
        new_clusters = [
            c for c in clusters
            if c.get("cluster_id") not in prev_ids and not c.get("is_noise")
        ]

        if not new_clusters:
            return []

        for c in new_clusters:
            await self._dispatch({
                "type": "mining.new_cluster",
                "severity": "warning",
                "title": f"New error cluster detected: {c.get('error_type', 'Unknown')}",
                "body": (
                    f"Novel pattern '{c.get('error_type', 'Unknown')}' "
                    f"emerged with {c.get('size', 0)} occurrences. "
                    f"Sample: {c.get('representative_error', '')[:200]}"
                ),
                "cluster": c,
                "timestamp": datetime.utcnow().isoformat(),
            })

        return new_clusters

    async def notify_velocity_spikes(
        self,
        velocity_data: List[Dict[str, Any]],
        spike_threshold: float = 2.0,
    ) -> List[Dict[str, Any]]:
        spikes = [
            v for v in velocity_data
            if abs(v.get("velocity", 0)) >= spike_threshold
            and v.get("trend") == "accelerating"
        ]

        if not spikes:
            return []

        for v in spikes:
            await self._dispatch({
                "type": "mining.velocity_spike",
                "severity": "high",
                "title": f"Velocity spike: {v.get('error_type', 'Unknown')}",
                "body": (
                    f"Error type '{v.get('error_type', 'Unknown')}' "
                    f"is accelerating (velocity={v.get('velocity', 0)}). "
                    f"Avg {v.get('avg_daily', 0)} occurrences/day. "
                    f"Cluster #{v.get('cluster_id')}"
                ),
                "velocity_data": v,
                "timestamp": datetime.utcnow().isoformat(),
            })

        return spikes

    async def notify_cascade_root(
        self,
        root_clusters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not root_clusters:
            return []

        for r in root_clusters[:1]:
            await self._dispatch({
                "type": "mining.cascade_root",
                "severity": "info",
                "title": f"Cascade root identified: {r.get('error_type', 'Unknown')}",
                "body": (
                    f"Cluster #{r.get('cluster_id')} ({r.get('error_type')}) "
                    f"appears first in {r.get('cascade_count', 0)} cascades. "
                    f"Fixing this root may eliminate downstream alerts."
                ),
                "root_data": r,
                "timestamp": datetime.utcnow().isoformat(),
            })

        return root_clusters

    async def _dispatch(self, payload: Dict[str, Any]):
        if not self.webhook_url:
            logger.debug(
                f"Notifier: no webhook_url set, skipped notification "
                f"type={payload.get('type')}"
            )
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f"Notifier: webhook returned {resp.status} "
                            f"for {payload.get('type')}"
                        )
                    else:
                        logger.info(
                            f"Notifier: {payload.get('type')} "
                            f"dispatched to {self.webhook_url}"
                        )
        except Exception as e:
            logger.warning(
                f"Notifier: dispatch failed for {payload.get('type')}: {e}"
            )
