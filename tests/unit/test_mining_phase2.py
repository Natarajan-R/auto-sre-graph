import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from datetime import datetime, timedelta
import asyncio

from src.mining.scheduler import MiningScheduler
from src.mining.notifier import MiningNotifier
from src.mining.persist import MiningPersist


class TestMiningScheduler:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        scheduler = MiningScheduler(interval_minutes=60)
        assert not scheduler.running

        await scheduler.start()
        assert scheduler.running
        assert scheduler._task is not None

        await scheduler.stop()
        assert not scheduler.running
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_handler_called(self):
        scheduler = MiningScheduler(interval_minutes=0.01)
        handler = AsyncMock()
        scheduler.set_handler(handler)

        await scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()

        assert handler.awaited

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash(self):
        scheduler = MiningScheduler(interval_minutes=0.01)

        async def failing_handler():
            raise RuntimeError("test error")

        scheduler.set_handler(failing_handler)
        await scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()

        assert not scheduler.running

    @pytest.mark.asyncio
    async def test_no_handler_warning(self):
        scheduler = MiningScheduler(interval_minutes=60)
        await scheduler.start()
        assert scheduler.running
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_double_start(self):
        scheduler = MiningScheduler(interval_minutes=60)
        await scheduler.start()
        await scheduler.start()
        assert scheduler.running
        await scheduler.stop()

    def test_default_interval(self):
        scheduler = MiningScheduler()
        assert scheduler.interval == timedelta(minutes=60)

    def test_custom_interval(self):
        scheduler = MiningScheduler(interval_minutes=30)
        assert scheduler.interval == timedelta(minutes=30)


class TestMiningNotifier:
    def setup_method(self):
        self.clusters = [
            {"cluster_id": 0, "error_type": "Connection/Timeout", "size": 15, "representative_error": "timeout", "is_noise": False},
            {"cluster_id": 1, "error_type": "Auth", "size": 1, "representative_error": "auth", "is_noise": True},
            {"cluster_id": 2, "error_type": "Memory", "size": 8, "representative_error": "OOM", "is_noise": False},
        ]

        self.previous_clusters = [
            {"cluster_id": 0, "error_type": "Connection/Timeout", "size": 10},
        ]

    @pytest.mark.asyncio
    async def test_notify_new_clusters(self):
        notifier = MiningNotifier()
        new = await notifier.notify_new_clusters(self.clusters, self.previous_clusters)
        cluster_ids = {c["cluster_id"] for c in new}
        assert 1 not in cluster_ids
        assert 2 in cluster_ids
        assert 0 not in cluster_ids

    @pytest.mark.asyncio
    async def test_notify_new_clusters_skips_noise(self):
        notifier = MiningNotifier()
        new = await notifier.notify_new_clusters(self.clusters, [])
        noise = [c for c in new if c.get("is_noise")]
        assert len(noise) == 0

    @pytest.mark.asyncio
    async def test_notify_new_clusters_empty(self):
        notifier = MiningNotifier()
        new = await notifier.notify_new_clusters([], [])
        assert new == []

    @pytest.mark.asyncio
    async def test_notify_velocity_spikes(self):
        notifier = MiningNotifier()
        velocity_data = [
            {"cluster_id": 0, "velocity": 3.5, "trend": "accelerating", "error_type": "Timeout", "avg_daily": 5.0},
            {"cluster_id": 1, "velocity": 0.2, "trend": "stable", "error_type": "Auth", "avg_daily": 2.0},
            {"cluster_id": 2, "velocity": -1.0, "trend": "declining", "error_type": "Memory", "avg_daily": 3.0},
        ]
        spikes = await notifier.notify_velocity_spikes(velocity_data, spike_threshold=2.0)
        assert len(spikes) == 1
        assert spikes[0]["cluster_id"] == 0

    @pytest.mark.asyncio
    async def test_notify_velocity_spikes_no_spikes(self):
        notifier = MiningNotifier()
        velocity_data = [
            {"cluster_id": 0, "velocity": 0.5, "trend": "stable", "error_type": "Timeout", "avg_daily": 5.0},
        ]
        spikes = await notifier.notify_velocity_spikes(velocity_data)
        assert spikes == []

    @pytest.mark.asyncio
    async def test_notify_cascade_root(self):
        notifier = MiningNotifier()
        roots = [
            {"cluster_id": 0, "error_type": "Connection/Timeout", "cascade_count": 5},
        ]
        notified = await notifier.notify_cascade_root(roots)
        assert len(notified) == 1
        assert notified[0]["cluster_id"] == 0

    @pytest.mark.asyncio
    async def test_notify_cascade_root_empty(self):
        notifier = MiningNotifier()
        notified = await notifier.notify_cascade_root([])
        assert notified == []

    @pytest.mark.asyncio
    async def test_dispatch_without_url(self):
        notifier = MiningNotifier()
        result = await notifier._dispatch({"type": "test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_with_url(self):
        notifier = MiningNotifier(webhook_url="http://example.com/hook")
        payload = {"type": "mining.test", "body": "hello"}
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            await notifier._dispatch(payload)
            mock_post.assert_called_once()


class TestMiningPersistParseTs:
    def test_parse_ts_none(self):
        p = MiningPersist()
        assert p._parse_ts(None) is None

    def test_parse_ts_datetime(self):
        p = MiningPersist()
        dt = datetime(2026, 7, 30, 12, 0, 0)
        assert p._parse_ts(dt) == dt

    def test_parse_ts_iso_string(self):
        p = MiningPersist()
        result = p._parse_ts("2026-07-30T12:00:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 7

    def test_parse_ts_iso_string_z(self):
        p = MiningPersist()
        result = p._parse_ts("2026-07-30T12:00:00Z")
        assert result is not None

    def test_parse_ts_invalid(self):
        p = MiningPersist()
        assert p._parse_ts("not-a-date") is None


class TestMiningPersist:
    def _make_persist(self):
        p = MiningPersist()
        p._connect = AsyncMock()
        p._conn = MagicMock()
        return p

    @pytest.mark.asyncio
    async def test_get_mining_metrics_empty(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={
            "total_snapshots": 0,
            "total_clusters": 0,
            "real_clusters": 0,
            "accelerating_clusters": 0,
            "total_events": 0,
            "avg_non_stable_velocity": 0.0,
        })
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        m = await p.get_mining_metrics()
        assert m["total_snapshots"] == 0
        assert m["total_clusters"] == 0
        assert m["total_events"] == 0

    @pytest.mark.asyncio
    async def test_get_mining_metrics_with_data(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={
            "total_snapshots": 5,
            "total_clusters": 42,
            "real_clusters": 38,
            "accelerating_clusters": 3,
            "total_events": 1500,
            "avg_non_stable_velocity": 2.5,
        })
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        m = await p.get_mining_metrics()
        assert m["total_snapshots"] == 5
        assert m["total_clusters"] == 42
        assert m["accelerating_clusters"] == 3

    @pytest.mark.asyncio
    async def test_save_cluster_snapshot(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(side_effect=[
            {"id": "uuid-1"},
            {"id": "uuid-2"},
        ])
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        p._conn.commit = AsyncMock()

        clusters = [
            {
                "cluster_id": 0,
                "error_type": "Connection/Timeout",
                "representative_error": "timeout after 30s",
                "size": 5,
                "services": ["payment"],
                "severities": ["HIGH"],
                "first_seen": "2026-07-30T10:00:00",
                "last_seen": "2026-07-30T12:00:00",
                "is_noise": False,
                "members": [
                    {"thread_id": "t1", "alert_id": "a1", "timestamp": "2026-07-30T11:00:00",
                     "service_name": "payment", "environment": "prod",
                     "error_message": "timeout", "severity": "HIGH"},
                ],
            }
        ]
        now = datetime.utcnow()
        saved = await p.save_cluster_snapshot(clusters, "2026073012", now - timedelta(hours=1), now)
        assert saved == 1

    @pytest.mark.asyncio
    async def test_load_clusters(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[
            {"id": "uuid-1", "cluster_id": 0, "error_type": "Timeout", "size": 10},
        ])
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        results = await p.load_clusters(period="2026073012")
        assert len(results) == 1
        assert results[0]["error_type"] == "Timeout"

    @pytest.mark.asyncio
    async def test_load_cluster_events(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[
            {"id": "evt-1", "thread_id": "t1", "error_message": "timeout", "service_name": "payment"},
        ])
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        results = await p.load_cluster_events("uuid-1")
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_period(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"snapshot_period": "2026073012"})
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        period = await p.get_latest_snapshot_period()
        assert period == "2026073012"

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_period_none(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        period = await p.get_latest_snapshot_period()
        assert period is None

    @pytest.mark.asyncio
    async def test_get_velocity_history(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[
            {"snapshot_period": "2026073012", "size": 10, "velocity": 2.5, "trend": "accelerating",
             "snapshot_start": datetime(2026, 7, 30, 12, 0), "snapshot_end": datetime(2026, 7, 30, 13, 0)},
        ])
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        history = await p.get_velocity_history("Connection/Timeout")
        assert len(history) == 1
        assert history[0]["velocity"] == 2.5

    @pytest.mark.asyncio
    async def test_update_velocity(self):
        p = self._make_persist()
        mock_cur = AsyncMock()
        p._conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cur),
            __aexit__=AsyncMock(),
        ))
        p._conn.commit = AsyncMock()
        await p.update_velocity(0, "2026073012", 3.0, "accelerating")
        mock_cur.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self):
        p = MiningPersist()
        p._conn = MagicMock()
        p._conn.closed = False
        p._conn.close = AsyncMock()
        await p.close()
        p._conn.close.assert_awaited_once()
