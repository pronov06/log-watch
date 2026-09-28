"""Tests for alert publishers and dispatcher."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.config import Settings
from app.models import Alert
from app.publishers.console import ConsolePublisher
from app.publishers.dispatcher import Dispatcher
from app.publishers.cloudwatch import CloudWatchPublisher
from app.publishers.sns import SnsPublisher


@pytest.fixture
def sample_alert() -> Alert:
    return Alert(
        id="test-alert-12345",
        event="OPENED",
        severity="HIGH",
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
    pub = ConsolePublisher()
    status = await pub.publish(sample_alert)
    assert status == "ok"


@pytest.mark.asyncio
async def test_dispatcher_dry_run(sample_alert):
    cfg = Settings(publish_mode="dry_run")
    queue = asyncio.Queue()
    dispatcher = Dispatcher(cfg, queue)

    worker_task = asyncio.create_task(dispatcher.run())
    try:
        await queue.put(sample_alert)
        # Give dispatcher cycle to process
        await asyncio.sleep(0.1)
        assert sample_alert.publish_status.get("console") == "ok"
    finally:
        dispatcher.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_cloudwatch_publisher_mocked(sample_alert):
    pub = CloudWatchPublisher(
        log_group="/test/group",
        log_stream="alerts",
        region="ap-south-1",
    )

    mock_client = MagicMock()
    with patch.object(pub, "_get_client", return_value=mock_client):
        res = await pub.publish(sample_alert)
        assert res == "ok"
        mock_client.put_log_events.assert_called_once()


@pytest.mark.asyncio
async def test_sns_publisher_mocked(sample_alert):
    pub = SnsPublisher(
        topic_arn="arn:aws:sns:ap-south-1:123456789012:test-topic",
        region="ap-south-1",
        min_severity="MEDIUM",
    )

    mock_client = MagicMock()
    with patch.object(pub, "_get_client", return_value=mock_client):
        res = await pub.publish(sample_alert)
        assert res == "ok"
        mock_client.publish.assert_called_once()
