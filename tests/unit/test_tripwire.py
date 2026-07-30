import pytest
import time
import re
from src.tools.tripwire import DebounceCapacitor, TripwireConfig, TripwireDaemon


class TestDebounceCapacitor:
    def test_first_occurrence_not_suppressed(self):
        cap = DebounceCapacitor(ttl_seconds=60)
        assert cap.is_suppressed("error: connection timeout") is False

    def test_duplicate_within_ttl_is_suppressed(self):
        cap = DebounceCapacitor(ttl_seconds=60)
        msg = "error: connection timeout"
        assert cap.is_suppressed(msg) is False
        assert cap.is_suppressed(msg) is True

    def test_duplicate_after_ttl_expires(self):
        cap = DebounceCapacitor(ttl_seconds=0.1)
        msg = "error: timeout"
        assert cap.is_suppressed(msg) is False
        time.sleep(0.15)
        assert cap.is_suppressed(msg) is False

    def test_different_messages_not_suppressed(self):
        cap = DebounceCapacitor(ttl_seconds=60)
        assert cap.is_suppressed("error A") is False
        assert cap.is_suppressed("error B") is False

    def test_cache_cleanup(self):
        cap = DebounceCapacitor(ttl_seconds=0.05)
        cap.is_suppressed("old error")
        assert len(cap._cache) == 1
        time.sleep(0.1)
        cap.is_suppressed("new error")
        assert len(cap._cache) == 1


class TestTripwireConfig:
    def test_default_config(self):
        config = TripwireConfig()
        assert config.log_path == "/var/log/shared/application.log"
        assert config.webhook_url == "http://api:8000/webhooks/ado"
        assert config.environment == "PROD"
        assert config.service_name == "legacy-monolith"
        assert config.error_pattern == r"(?i)(error|exception|critical|fatal|traceback)"
        assert config.debounce_ttl == 60
        assert config.max_buffer_lines == 15
        assert config.poll_interval == 0.1

    def test_custom_config(self):
        config = TripwireConfig(
            log_path="/tmp/test.log",
            webhook_url="http://localhost:8000/webhooks/tripwire",
            environment="DEV",
            service_name="test-service",
            error_pattern=r"(?i)(CRITICAL)",
            debounce_ttl=30,
            max_buffer_lines=5,
            poll_interval=0.5,
        )
        assert config.log_path == "/tmp/test.log"
        assert config.webhook_url == "http://localhost:8000/webhooks/tripwire"
        assert config.environment == "DEV"
        assert config.service_name == "test-service"
        assert config.debounce_ttl == 30
        assert config.max_buffer_lines == 5
        assert config.poll_interval == 0.5


class TestTripwireDaemon:
    def test_init_default_config(self):
        daemon = TripwireDaemon()
        assert daemon.config.log_path == "/var/log/shared/application.log"
        assert daemon.config.webhook_url == "http://api:8000/webhooks/ado"
        assert daemon.config.service_name == "legacy-monolith"
        assert daemon.debouncer.ttl == 60
        assert daemon.is_capturing is False
        assert daemon.capture_buffer == []

    def test_init_custom_config(self):
        config = TripwireConfig(service_name="payment-service", environment="PROD")
        daemon = TripwireDaemon(config)
        assert daemon.config.service_name == "payment-service"
        assert daemon.config.environment == "PROD"

    def test_regex_compiles(self):
        daemon = TripwireDaemon()
        assert daemon.error_pattern == re.compile(daemon.config.error_pattern)

    def test_error_pattern_matches(self):
        daemon = TripwireDaemon()
        assert daemon.error_pattern.search("ERROR: connection refused")
        assert daemon.error_pattern.search("Critical: disk full")
        assert daemon.error_pattern.search("Fatal error")
        assert daemon.error_pattern.search("Traceback (most recent call last):")
        assert daemon.error_pattern.search("Exception: value error")
        assert not daemon.error_pattern.search("INFO: request completed")
        assert not daemon.error_pattern.search("DEBUG: processing batch")
        assert not daemon.error_pattern.search("WARNING: high memory usage")

    def test_capture_buffer_management(self):
        daemon = TripwireDaemon()
        assert daemon.is_capturing is False
        assert daemon.capture_buffer == []

        daemon.is_capturing = True
        daemon.capture_buffer.append("error line 1")
        assert len(daemon.capture_buffer) == 1

    def test_alert_id_format(self, monkeypatch):
        import hashlib
        config = TripwireConfig(service_name="payment-service")
        daemon = TripwireDaemon(config)
        msg = "test error"
        expected_hash = hashlib.md5(msg.encode()).hexdigest()[:8]
        timestamp = int(time.time())

        alert_id = f"TRIPWIRE-{timestamp}-{expected_hash}"
        assert alert_id.startswith("TRIPWIRE-")
        assert alert_id.endswith(expected_hash)
