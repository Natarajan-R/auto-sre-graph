import asyncio
import logging
from typing import Callable, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)


class MiningScheduler:
    def __init__(self, interval_minutes: int = 60):
        self.interval = timedelta(minutes=interval_minutes)
        self._task: Optional[asyncio.Task] = None
        self._active = False
        self._handler: Optional[Callable] = None

    def set_handler(self, handler: Callable):
        self._handler = handler

    async def start(self):
        if self._active:
            logger.warning("MiningScheduler already running")
            return
        self._active = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"MiningScheduler started (interval={self.interval})")

    async def stop(self):
        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MiningScheduler stopped")

    async def _run_loop(self):
        while self._active:
            try:
                if self._handler:
                    logger.info("Starting scheduled mining run")
                    await self._handler()
                    logger.info("Scheduled mining run complete")
                else:
                    logger.warning("No handler set for MiningScheduler")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Mining run failed: {e}", exc_info=True)

            await asyncio.sleep(self.interval.total_seconds())

    @property
    def running(self) -> bool:
        return self._active
