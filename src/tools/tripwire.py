# src/tools/tripwire.py
import asyncio
import hashlib
import time
import re
import os
import logging
import aiohttp
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class DebounceCapacitor:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._cache: Dict[str, float] = {}

    def is_suppressed(self, error_message: str) -> bool:
        current_time = time.time()
        error_hash = hashlib.sha256(error_message.encode()).hexdigest()

        if error_hash in self._cache and (current_time - self._cache[error_hash] < self.ttl):
            return True

        self._cache[error_hash] = current_time
        self._cleanup(current_time)
        return False

    def _cleanup(self, current_time: float):
        expired = [k for k, v in self._cache.items() if current_time - v >= self.ttl]
        for k in expired:
            del self._cache[k]


@dataclass
class TripwireConfig:
    log_path: str = "/var/log/shared/application.log"
    webhook_url: str = "http://api:8000/webhooks/ado"
    environment: str = "PROD"
    service_name: str = "legacy-monolith"
    error_pattern: str = r"(?i)(error|exception|critical|fatal|traceback)"
    debounce_ttl: int = 60
    max_buffer_lines: int = 15
    poll_interval: float = 0.1


class TripwireDaemon:
    def __init__(self, config: Optional[TripwireConfig] = None):
        self.config = config or TripwireConfig(
            log_path=os.getenv("TARGET_LOG", "/var/log/shared/application.log"),
            webhook_url=os.getenv("WEBHOOK_DESTINATION", "http://api:8000/webhooks/ado"),
            environment=os.getenv("ENVIRONMENT", "PROD"),
            service_name=os.getenv("SERVICE_NAME", "legacy-monolith"),
        )
        self.debouncer = DebounceCapacitor(ttl_seconds=self.config.debounce_ttl)
        self.error_pattern = re.compile(self.config.error_pattern)
        self.is_capturing = False
        self.capture_buffer: list[str] = []

    async def dispatch_alert(self, session: aiohttp.ClientSession, error_msg: str, stack_trace: str):
        if self.debouncer.is_suppressed(error_msg):
            return

        alert_id = f"TRIPWIRE-{int(time.time())}-{hashlib.md5(error_msg.encode()).hexdigest()[:8]}"

        payload = {
            "alert_id": alert_id,
            "environment": self.config.environment,
            "service_name": self.config.service_name,
            "severity": "HIGH",
            "error_message": error_msg,
            "stack_trace": stack_trace,
        }

        try:
            async with session.post(self.config.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    logger.info(f"Signal dispatched: {alert_id}")
                else:
                    body = await response.text()
                    logger.warning(f"Dispatch returned {response.status} for {alert_id}: {body}")
        except Exception as e:
            logger.error(f"Dispatch failed for {alert_id}: {e}")

    async def tail_and_parse(self):
        async with aiohttp.ClientSession() as session:
            with open(self.config.log_path, "r") as file:
                file.seek(0, 2)

                while True:
                    line = file.readline()
                    if not line:
                        await asyncio.sleep(self.config.poll_interval)
                        continue

                    line = line.rstrip("\n\r")

                    if self.is_capturing:
                        self.capture_buffer.append(line)
                        if len(self.capture_buffer) >= self.config.max_buffer_lines:
                            asyncio.create_task(self.dispatch_alert(
                                session,
                                self.capture_buffer[0],
                                "\n".join(self.capture_buffer[1:]),
                            ))
                            self.is_capturing = False
                            self.capture_buffer = []
                        continue

                    if self.error_pattern.search(line):
                        self.is_capturing = True
                        self.capture_buffer = [line]

    async def run(self):
        logger.info(f"Tripwire starting: {self.config.log_path} -> {self.config.webhook_url}")
        while True:
            try:
                await self.tail_and_parse()
            except FileNotFoundError:
                logger.warning(f"Log file not found: {self.config.log_path}. Retrying in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Tripwire error: {e}. Restarting in 5s...")
                await asyncio.sleep(5)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] TRIPWIRE: %(message)s",
    )

    config = TripwireConfig(
        log_path=os.getenv("TARGET_LOG", "/var/log/shared/application.log"),
        webhook_url=os.getenv("WEBHOOK_DESTINATION", "http://api:8000/webhooks/ado"),
        environment=os.getenv("ENVIRONMENT", "PROD"),
        service_name=os.getenv("SERVICE_NAME", "legacy-monolith"),
    )

    daemon = TripwireDaemon(config)
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
