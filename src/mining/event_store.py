from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
import psycopg
from psycopg.rows import dict_row
from src.config.settings import settings

logger = logging.getLogger(__name__)


class MiningEventStore:
    def __init__(self):
        self._conn = None

    async def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = await psycopg.AsyncConnection.connect(
                settings.postgres_uri,
                row_factory=dict_row,
            )

    async def get_events(
        self,
        days: int = 7,
        service: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        await self._connect()
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = """
            SELECT
                thread_id,
                checkpoint,
                checkpoint_id,
                parent_checkpoint_id,
                created_at
            FROM checkpoint_blobs
            WHERE created_at >= %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        params = [cutoff, limit]

        if service:
            query = query.replace("ORDER BY", "AND checkpoint->'values'->'alert'->>'service_name' = %s ORDER BY")
            params.insert(1, service)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        events = []
        for row in rows:
            checkpoint = row["checkpoint"]
            values = checkpoint.get("values", {}) if isinstance(checkpoint, dict) else {}
            alert = values.get("alert") or {}
            analysis = values.get("analysis")

            events.append({
                "thread_id": row["thread_id"],
                "alert_id": alert.get("alert_id", row["thread_id"]),
                "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                "service_name": alert.get("service_name", "unknown"),
                "environment": alert.get("environment", "unknown"),
                "error_message": alert.get("error_message", ""),
                "stack_trace": alert.get("stack_trace", ""),
                "severity": alert.get("severity", "HIGH"),
                "final_status": values.get("final_status", "unknown"),
                "analysis": analysis,
            })

        logger.info(f"Retrieved {len(events)} events from store (days={days}, service={service})")
        return events

    async def get_timeline(
        self,
        days: int = 7,
        granularity: str = "hour",
    ) -> List[Dict[str, Any]]:
        await self._connect()
        cutoff = datetime.utcnow() - timedelta(days=days)

        if granularity == "hour":
            date_trunc = "date_trunc('hour', created_at)"
        elif granularity == "day":
            date_trunc = "date_trunc('day', created_at)"
        else:
            date_trunc = "date_trunc('hour', created_at)"

        query = f"""
            SELECT
                {date_trunc} AS bucket,
                COUNT(*) AS event_count
            FROM checkpoint_blobs
            WHERE created_at >= %s
            GROUP BY bucket
            ORDER BY bucket ASC
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, [cutoff])
            rows = await cur.fetchall()

        return [
            {
                "timestamp": row["bucket"].isoformat() if row["bucket"] else None,
                "count": row["event_count"],
            }
            for row in rows
        ]

    async def get_service_counts(self, days: int = 7) -> List[Dict[str, Any]]:
        await self._connect()
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = """
            WITH service_errors AS (
                SELECT
                    checkpoint->'values'->'alert'->>'service_name' AS service_name,
                    COUNT(*) AS error_count,
                    MAX(created_at) AS last_seen
                FROM checkpoint_blobs
                WHERE created_at >= %s
                GROUP BY service_name
            )
            SELECT * FROM service_errors ORDER BY error_count DESC
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, [cutoff])
            return await cur.fetchall()

    async def close(self):
        if self._conn and not self._conn.closed:
            await self._conn.close()
