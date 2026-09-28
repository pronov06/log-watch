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


# --- byte-exact reads, rotation, late files, multi-source -------------------

from app.tailer import MultiTailer, expand_sources  # noqa: E402


async def _drain(queue: asyncio.Queue, n: int, timeout: float = 2.0) -> list[str]:
    return [await asyncio.wait_for(queue.get(), timeout=timeout) for _ in range(n)]


async def _run(tailer):
    task = asyncio.create_task(tailer.run())
    await asyncio.sleep(0.1)
    return task


async def _stop(tailer, task):
    tailer.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_tailer_handles_crlf_and_split_utf8(tmp_path):
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    queue = asyncio.Queue()
    tailer = Tailer(log, queue, poll_interval=0.02, from_start=True)
    task = await _run(tailer)
    try:
        snow = "café ☃".encode("utf-8")
        with open(log, "ab") as f:
            f.write(b"first\r\n" + snow[:-2])  # split inside the multi-byte snowman
        await asyncio.sleep(0.1)
        with open(log, "ab") as f:
            f.write(snow[-2:] + b"\r\nthird\n")
        assert await _drain(queue, 3) == ["first", "café ☃", "third"]
        assert tailer._offset == log.stat().st_size
    finally:
        await _stop(tailer, task)


@pytest.mark.asyncio
async def test_tailer_follows_rename_rotation(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("old 1\n")
    queue = asyncio.Queue()
    tailer = Tailer(log, queue, poll_interval=0.02, from_start=True)
    task = await _run(tailer)
    try:
        assert await _drain(queue, 1) == ["old 1"]
        log.rename(tmp_path / "app.log.1")
        log.write_text("new 1\nnew 2\n")  # new file, new identity, may be larger than old offset
        assert await _drain(queue, 2) == ["new 1", "new 2"]
    finally:
        await _stop(tailer, task)


@pytest.mark.asyncio
async def test_tailer_reads_file_created_after_start_from_beginning(tmp_path):
    log = tmp_path / "late.log"
    queue = asyncio.Queue()
    tailer = Tailer(log, queue, poll_interval=0.02)  # default: from EOF for existing files
    task = await _run(tailer)
    try:
        log.write_text("born 1\nborn 2\n")
        assert await _drain(queue, 2) == ["born 1", "born 2"]
    finally:
        await _stop(tailer, task)


@pytest.mark.asyncio
async def test_tailer_existing_file_starts_at_eof(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("history\n")
    queue = asyncio.Queue()
    tailer = Tailer(log, queue, poll_interval=0.02)
    task = await _run(tailer)
    try:
        with open(log, "a") as f:
            f.write("fresh\n")
        assert await _drain(queue, 1) == ["fresh"]
    finally:
        await _stop(tailer, task)


def test_expand_sources_keeps_plain_paths_and_matches_globs(tmp_path):
    (tmp_path / "a.log").write_text("")
    (tmp_path / "b.log").write_text("")
    (tmp_path / "c.txt").write_text("")
    found = expand_sources([str(tmp_path / "*.log"), str(tmp_path / "missing.log")])
    assert {p.name for p in found} == {"a.log", "b.log", "missing.log"}


@pytest.mark.asyncio
async def test_multitailer_picks_up_new_glob_matches(tmp_path):
    (tmp_path / "one.log").write_text("")
    queue = asyncio.Queue()
    mt = MultiTailer([str(tmp_path / "*.log")], queue, poll_interval=0.02, rescan_interval=0.05)
    task = asyncio.create_task(mt.run())
    try:
        await asyncio.sleep(0.15)
        with open(tmp_path / "one.log", "a") as f:
            f.write("from one\n")
        (tmp_path / "two.log").write_text("from two\n")  # appears later → read from start
        got = set(await _drain(queue, 2))
        assert got == {"from one", "from two"}
        assert len(mt.files) == 2 and mt.lines_read == 2
    finally:
        mt.stop()
        await asyncio.gather(task, return_exceptions=True)
