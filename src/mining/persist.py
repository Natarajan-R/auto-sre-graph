import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MiningPersist:
    def __init__(self):
        self._conn = None
        self._psycopg = None

    def _load_psycopg(self):
        if self._psycopg is None:
            import psycopg
            from psycopg.rows import dict_row
            self._psycopg = psycopg
            self._dict_row = dict_row
        return self._psycopg, self._dict_row

    async def _connect(self):
        from src.config.settings import settings
        psycopg, dict_row = self._load_psycopg()
        if self._conn is None or self._conn.closed:
            self._conn = await psycopg.AsyncConnection.connect(
                settings.postgres_uri,
                row_factory=dict_row,
            )

    async def save_cluster_snapshot(
        self,
        clusters: List[Dict[str, Any]],
        period: str,
        start: datetime,
        end: datetime,
    ) -> int:
        await self._connect()
        saved = 0
        async with self._conn.cursor() as cur:
            for c in clusters:
                await cur.execute("""
                    INSERT INTO mining_clusters (
                        cluster_id, error_type, representative_error, size,
                        services, severities, first_seen, last_seen,
                        is_noise, snapshot_period, snapshot_start, snapshot_end
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (cluster_id, snapshot_period)
                    DO UPDATE SET
                        size = EXCLUDED.size,
                        last_seen = EXCLUDED.last_seen,
                        is_noise = EXCLUDED.is_noise
                    RETURNING id
                """, (
                    c.get("cluster_id"),
                    c.get("error_type", "Unknown"),
                    c.get("representative_error", "")[:500],
                    c.get("size", 0),
                    c.get("services", []),
                    c.get("severities", []),
                    self._parse_ts(c.get("first_seen")),
                    self._parse_ts(c.get("last_seen")),
                    c.get("is_noise", False),
                    period,
                    start,
                    end,
                ))
                row = await cur.fetchone()
                cluster_ref_id = row["id"] if row else None

                if cluster_ref_id and c.get("members"):
                    for m in c["members"]:
                        try:
                            await cur.execute("""
                                INSERT INTO mining_events (
                                    cluster_ref_id, thread_id, alert_id,
                                    timestamp, service_name, environment,
                                    error_message, severity, snapshot_period
                                ) VALUES (
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                                )
                            """, (
                                cluster_ref_id,
                                m.get("thread_id"),
                                m.get("alert_id"),
                                self._parse_ts(m.get("timestamp")),
                                m.get("service_name", "unknown"),
                                m.get("environment"),
                                m.get("error_message", "")[:2000],
                                m.get("severity", "HIGH"),
                                period,
                            ))
                        except Exception as e:
                            logger.debug(f"Skipping event insert: {e}")
                    saved += 1

        await self._conn.commit()
        logger.info(f"Saved {saved} clusters for period {period}")
        return saved

    async def load_clusters(
        self,
        period: Optional[str] = None,
        min_size: int = 1,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        await self._connect()
        query = """
            SELECT * FROM mining_clusters
            WHERE size >= %s
        """
        params = [min_size]

        if period:
            query += " AND snapshot_period = %s"
            params.append(period)

        query += " ORDER BY size DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            return [dict(r) for r in await cur.fetchall()]

    async def load_cluster_events(
        self,
        cluster_ref_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        await self._connect()
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM mining_events
                WHERE cluster_ref_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (cluster_ref_id, limit))
            return [dict(r) for r in await cur.fetchall()]

    async def get_velocity_history(
        self,
        error_type: str,
        max_snapshots: int = 30,
    ) -> List[Dict[str, Any]]:
        await self._connect()
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT snapshot_period, size, velocity, trend, snapshot_start, snapshot_end
                FROM mining_clusters
                WHERE error_type = %s
                ORDER BY snapshot_start DESC
                LIMIT %s
            """, (error_type, max_snapshots))
            return [dict(r) for r in await cur.fetchall()]

    async def update_velocity(
        self,
        cluster_id: int,
        period: str,
        velocity: float,
        trend: str,
    ):
        await self._connect()
        async with self._conn.cursor() as cur:
            await cur.execute("""
                UPDATE mining_clusters
                SET velocity = %s, trend = %s
                WHERE cluster_id = %s AND snapshot_period = %s
            """, (velocity, trend, cluster_id, period))
        await self._conn.commit()

    async def get_latest_snapshot_period(self) -> Optional[str]:
        await self._connect()
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT snapshot_period FROM mining_clusters
                ORDER BY snapshot_start DESC
                LIMIT 1
            """)
            row = await cur.fetchone()
            return row["snapshot_period"] if row else None

    async def get_mining_metrics(self) -> Dict[str, Any]:
        await self._connect()
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    COUNT(DISTINCT snapshot_period) AS total_snapshots,
                    COUNT(*) AS total_clusters,
                    COUNT(*) FILTER (WHERE is_noise = FALSE) AS real_clusters,
                    COUNT(*) FILTER (WHERE trend = 'accelerating') AS accelerating_clusters,
                    COALESCE(SUM(size), 0) AS total_events,
                    COALESCE(AVG(velocity) FILTER (WHERE trend != 'stable'), 0.0) AS avg_non_stable_velocity
                FROM mining_clusters
            """)
            row = await cur.fetchone()
            return dict(row) if row else {}

    def _parse_ts(self, ts) -> Optional[datetime]:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                pass
        return None

    async def close(self):
        if self._conn and not self._conn.closed:
            await self._conn.close()
