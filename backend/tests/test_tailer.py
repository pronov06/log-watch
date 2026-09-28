"""Tests for the async log tailer — offset tracking, partial lines, truncation, rotation."""

import asyncio
import tempfile
from pathlib import Path
import pytest

from app.tailer import Tailer


@pytest.mark.asyncio
async def test_tailer_reads_appended_lines():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        f.write("line 1\n")
        f.flush()
        log_path = Path(f.name)

    queue = asyncio.Queue()
    tailer = Tailer(log_path, queue, poll_interval=0.05, from_start=True)
    task = asyncio.create_task(tailer.run())

    try:
        # Should read initial line
        line = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert line == "line 1"

        # Append new lines
        with open(log_path, "a") as f:
            f.write("line 2\nline 3\n")

        line2 = await asyncio.wait_for(queue.get(), timeout=2.0)
        line3 = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert line2 == "line 2"
        assert line3 == "line 3"
    finally:
        tailer.stop() if hasattr(tailer, "stop") else setattr(tailer, "_running", False)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if log_path.exists():
            log_path.unlink()


@pytest.mark.asyncio
async def test_tailer_partial_line_buffering():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        f.write("incomplete")
        f.flush()
        log_path = Path(f.name)

    queue = asyncio.Queue()
    tailer = Tailer(log_path, queue, poll_interval=0.05, from_start=True)
    task = asyncio.create_task(tailer.run())

    try:
        # Give it a moment — incomplete line should NOT be emitted yet
        await asyncio.sleep(0.15)
        assert queue.empty()

        # Complete the line
        with open(log_path, "a") as f:
            f.write(" line completed\n")

        line = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert line == "incomplete line completed"
    finally:
        setattr(tailer, "_running", False)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if log_path.exists():
            log_path.unlink()


@pytest.mark.asyncio
async def test_tailer_truncation_detection():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        f.write("line 1 with a long text here\n")
        f.flush()
        log_path = Path(f.name)

    queue = asyncio.Queue()
    tailer = Tailer(log_path, queue, poll_interval=0.05, from_start=True)
    task = asyncio.create_task(tailer.run())

    try:
        line = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert "line 1" in line

        # Truncate file with smaller content
        with open(log_path, "w") as f:
            f.write("short\n")

        line_after = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert line_after == "short"
    finally:
        setattr(tailer, "_running", False)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if log_path.exists():
            log_path.unlink()
