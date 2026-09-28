"""Tests for alert publishers, the dispatcher and the CloudWatch metrics reporter (moto-backed)."""

import asyncio
import json

from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws

from app.bus import EventBus
from app.config import Settings
from app.models import Alert
from app.publishers.cloudwatch import (
    MAX_BATCH_BYTES,
    CloudWatchPublisher,
    chunk_events,
)
from app.publishers.console import ConsolePublisher
from app.publishers.dispatcher import Dispatcher
from app.publishers.metrics import NAMESPACE, MetricsReporter
from app.publishers.sns import SnsPublisher

REGION = "ap-south-1"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    # Never let tests touch a real account, even if the developer has credentials.
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": REGION,
    }.items():
        monkeypatch.setenv(k, v)


def _boom(**_):
    raise EndpointConnectionError(endpoint_url="https://logs.example")


@pytest.fixture
def sample_alert() -> Alert:
    return Alert(
        id="test-alert-12345",
        event="OPENED",
        severity="HIGH",
        peak_severity="HIGH",
        title="Error rate spike: 25.0% (baseline 2.0%)",
        error_rate=0.25,
        baseline_mean=0.02,
        z_score=6.8,
        window_seconds=60,
        top_errors=[{"message": "DB timeout", "count": 15}],
        opened_at="2026-09-28T10:00:00Z",
    )


@pytest.mark.asyncio
async def test_console_publisher(sample_alert):
    assert await ConsolePublisher().publish(sample_alert) == "ok"


# --- CloudWatch Logs ---------------------------------------------------------

@pytest.mark.asyncio
async def test_cloudwatch_creates_destination_and_writes_json(sample_alert):
    with mock_aws():
        pub = CloudWatchPublisher("/test/group", "alerts", REGION)
        assert await pub.publish(sample_alert) == "ok"

        logs = boto3.client("logs", region_name=REGION)
        events = logs.get_log_events(logGroupName="/test/group", logStreamName="alerts")["events"]
        assert len(events) == 1
        body = json.loads(events[0]["message"])
        assert body["alert_id"] == sample_alert.id
        assert body["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_cloudwatch_batch_is_one_call_per_chunk(sample_alert):
    with mock_aws():
        pub = CloudWatchPublisher("/test/group", "alerts", REGION)
        alerts = [sample_alert.model_copy(update={"id": f"a{i}"}) for i in range(5)]
        assert await pub.publish_batch(alerts) == "ok"
        logs = boto3.client("logs", region_name=REGION)
        events = logs.get_log_events(logGroupName="/test/group", logStreamName="alerts")["events"]
        assert len(events) == 5


@pytest.mark.asyncio
async def test_cloudwatch_recreates_deleted_stream(sample_alert):
    with mock_aws():
        pub = CloudWatchPublisher("/test/group", "alerts", REGION)
        await pub.publish(sample_alert)
        boto3.client("logs", region_name=REGION).delete_log_stream(
            logGroupName="/test/group", logStreamName="alerts")
        assert await pub.publish(sample_alert) == "ok"


@pytest.mark.asyncio
async def test_cloudwatch_raises_when_unreachable(sample_alert):
    pub = CloudWatchPublisher("/g", "s", REGION)
    missing = type("ResourceNotFoundException", (Exception,), {})
    pub._client = SimpleNamespace(
        exceptions=SimpleNamespace(ResourceNotFoundException=missing), put_log_events=_boom)
    pub._ensured = True
    with pytest.raises(EndpointConnectionError):
        await pub.publish(sample_alert)


def test_chunk_events_respects_byte_limit():
    big = "x" * 200_000
    events = [{"timestamp": i, "message": big} for i in range(12)]
    batches = chunk_events(events)
    assert len(batches) > 1
    for b in batches:
        assert sum(len(e["message"]) + 26 for e in b) <= MAX_BATCH_BYTES
    assert sum(len(b) for b in batches) == 12


def test_chunk_events_respects_count_limit():
    events = [{"timestamp": i, "message": "m"} for i in range(10_001)]
    assert [len(b) for b in chunk_events(events)] == [10_000, 1]


# --- SNS ---------------------------------------------------------------------

def _sns_topic():
    return boto3.client("sns", region_name=REGION).create_topic(Name="log-anomaly-alerts")["TopicArn"]


@pytest.mark.asyncio
async def test_sns_publishes_above_min_severity(sample_alert):
    with mock_aws():
        pub = SnsPublisher(_sns_topic(), REGION, min_severity="MEDIUM")
        assert await pub.publish(sample_alert) == "ok"


@pytest.mark.asyncio
async def test_sns_skips_below_min_severity(sample_alert):
    with mock_aws():
        pub = SnsPublisher(_sns_topic(), REGION, min_severity="HIGH")
        low = sample_alert.model_copy(update={"severity": "LOW", "peak_severity": "LOW"})
        assert await pub.publish(low) == "skipped"


@pytest.mark.asyncio
async def test_sns_resolved_uses_peak_severity(sample_alert):
    with mock_aws():
        pub = SnsPublisher(_sns_topic(), REGION, min_severity="MEDIUM")
        quiet = sample_alert.model_copy(update={"event": "RESOLVED", "severity": "LOW", "peak_severity": "LOW"})
        loud = sample_alert.model_copy(update={"event": "RESOLVED", "severity": "LOW", "peak_severity": "HIGH"})
        assert await pub.publish(quiet) == "skipped"
        assert await pub.publish(loud) == "ok"


# --- Dispatcher --------------------------------------------------------------

class _FlakyPublisher:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def publish(self, alert):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("throttled")
        return "ok"


def _dispatcher(bus=None, retries=3):
    cfg = Settings(publish_mode="dry_run", publish_max_retries=retries, publish_backoff_base_sec=0.001)
    return Dispatcher(cfg, asyncio.Queue(), bus=bus)


@pytest.mark.asyncio
async def test_dispatcher_retries_then_succeeds(sample_alert):
    d = _dispatcher()
    flaky = _FlakyPublisher(failures=2)
    d.publishers = [("flaky", flaky)]
    await d._dispatch([sample_alert])
    assert flaky.calls == 3
    assert sample_alert.publish_status == {"flaky": "ok"}
    assert d.failures == 2


@pytest.mark.asyncio
async def test_dispatcher_gives_up_after_max_retries(sample_alert):
    d = _dispatcher(retries=2)
    d.publishers = [("flaky", _FlakyPublisher(failures=99))]
    await d._dispatch([sample_alert])
    assert sample_alert.publish_status == {"flaky": "failed"}
    assert "throttled" in d.last_error


@pytest.mark.asyncio
async def test_dispatcher_pushes_status_to_bus(sample_alert):
    bus = EventBus()
    bus.publish("alert", sample_alert.model_dump())
    q = bus.subscribe()
    d = _dispatcher(bus=bus)
    task = asyncio.create_task(d.run())
    try:
        await d.alert_queue.put(sample_alert)
        env = await asyncio.wait_for(q.get(), timeout=2)
        assert env.type == "alert_update"
        assert env.data["publish_status"] == {"console": "ok"}
        assert bus.get_alerts()[0]["publish_status"] == {"console": "ok"}
    finally:
        d.stop()
        await task


@pytest.mark.asyncio
async def test_dispatcher_shutdown_flushes_queue(sample_alert):
    d = _dispatcher()
    await d.alert_queue.put(sample_alert)
    await d.shutdown(timeout=2)
    assert d.alert_queue.empty()
    assert sample_alert.publish_status == {"console": "ok"}


@pytest.mark.asyncio
async def test_dispatcher_aws_mode_end_to_end(sample_alert):
    with mock_aws():
        topic = _sns_topic()
        cfg = Settings(publish_mode="aws", sns_topic_arn=topic, cw_log_group="/t/g", cw_log_stream="s",
                       aws_region=REGION, publish_backoff_base_sec=0.001)
        d = Dispatcher(cfg, asyncio.Queue())
        await d._dispatch([sample_alert])
        assert sample_alert.publish_status == {"console": "ok", "cloudwatch": "ok", "sns": "ok"}


# --- CloudWatch metrics ------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_reporter_flushes_buffer():
    with mock_aws():
        r = MetricsReporter(REGION, open_alerts=lambda: 1)
        for rate in (0.02, 0.03, 0.4):
            r.add({"error_rate": rate, "z": 1.0, "events_per_sec": 30.0})
        await r.flush()
        assert r.flushes == 1 and r._buffer == []
        names = {m["MetricName"] for m in
                 boto3.client("cloudwatch", region_name=REGION).list_metrics(Namespace=NAMESPACE)["Metrics"]}
        assert {"ErrorRate", "ZScore", "EventsPerSec", "OpenAlerts"} <= names


@pytest.mark.asyncio
async def test_metrics_reporter_failure_is_not_fatal():
    r = MetricsReporter(REGION)
    r._client = SimpleNamespace(put_metric_data=_boom)
    r.add({"error_rate": 0.1, "z": None, "events_per_sec": 1.0})
    await r.flush()
    assert r.failures == 1 and r.last_error
