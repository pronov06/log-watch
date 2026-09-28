"""
Async file tailers — read new lines from growing log files.

Tailer (one file):
- Offset-based polling (no inotify dependency, works cross-platform)
- Byte-exact offsets: reads in binary and decodes complete lines only, so CRLF files
  and multi-byte UTF-8 split across reads never corrupt the position or a character
- Truncation detection: if file size < offset, reset to 0
- Rotation detection: if the file identity (st_ino; NTFS file index on Windows) changes
- Partial-line buffering: holds back the last line if it doesn't end with \\n
- Bounded asyncio.Queue output: drops oldest lines with a counter if the consumer lags
- A file that doesn't exist yet is waited for, then read from its first byte
- Reads in chunks (up to 1 MB per poll) in a worker thread, never blocking the event loop

MultiTailer (many files):
- Expands comma-separated paths and glob patterns (e.g. /var/log/nginx/*.log)
- Rescans periodically so files created later are picked up automatically
"""

from __future__ import annotations

import asyncio
import glob
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 1_048_576  # 1 MB per poll cycle
_GLOB_CHARS = set("*?[")


class Tailer:
    """
    Async file tailer that yields lines via an asyncio.Queue.

    Usage:
        tailer = Tailer(path, queue, poll_interval=0.2)
        asyncio.create_task(tailer.run())
        # consume from queue
    """

    def __init__(
        self,
        path: str | Path,
        queue: asyncio.Queue,
        poll_interval: float = 0.2,
        from_start: bool = False,
    ):
        self.path = Path(path)
        self.queue = queue
        self.poll_interval = poll_interval
        self.from_start = from_start

        self._offset: int = 0
        self._inode: int | None = None
        self._partial: bytes = b""
        self._running: bool = False
        self.lines_read: int = 0
        self.lines_dropped: int = 0

    async def run(self) -> None:
        """Main loop — poll the file for new data."""
        self._running = True
        logger.info("Tailer starting: %s (from_start=%s)", self.path, self.from_start)

        # A file that appears after startup is entirely new data: read it from byte 0.
        existed_at_start = self.path.exists()
        while self._running and not self.path.exists():
            await asyncio.sleep(self.poll_interval * 5)

        if existed_at_start and not self.from_start:
            try:
                self._offset = self.path.stat().st_size
            except OSError:
                self._offset = 0

        self._inode = self._get_inode()
        logger.info("Tailer ready: %s at offset %d", self.path, self._offset)

        while self._running:
            try:
                await self._poll_once()
            except Exception as exc:
                logger.error("Tailer error on %s (will retry): %s", self.path, exc)
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        """One poll cycle: stat, detect rotation/truncation, read new data."""
        try:
            stat = self.path.stat()
        except OSError:
            return  # missing (mid-rotation); keep polling

        current_inode = getattr(stat, "st_ino", 0) or 0
        file_size = stat.st_size

        if current_inode != self._inode or file_size < self._offset:
            action = "rotated" if current_inode != self._inode else "truncated"
            logger.info("File %s %s (inode %s→%s, size %d), reading from 0",
                        self.path, action, self._inode, current_inode, file_size)
            self._offset = 0
            self._inode = current_inode
            self._partial = b""

        if file_size <= self._offset:
            return

        data = await asyncio.to_thread(self._read_chunk, file_size)
        if not data:
            return

        chunks = (self._partial + data).split(b"\n")
        self._partial = chunks.pop()  # b"" when data ended with \n, else an incomplete line

        for raw in chunks:
            line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
            if line:
                self._emit(line)

    def _emit(self, line: str) -> None:
        self.lines_read += 1
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            # Drop oldest to make room: the newest lines matter most for detection.
            try:
                self.queue.get_nowait()
                self.lines_dropped += 1
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(line)
            except asyncio.QueueFull:
                self.lines_dropped += 1

    def _read_chunk(self, file_size: int) -> bytes:
        """Read up to MAX_CHUNK_BYTES of new data (runs in a thread)."""
        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                data = f.read(min(file_size - self._offset, MAX_CHUNK_BYTES))
        except OSError as exc:
            logger.warning("Read error on %s: %s", self.path, exc)
            return b""
        self._offset += len(data)
        return data

    def _get_inode(self) -> int | None:
        try:
            return getattr(self.path.stat(), "st_ino", 0) or 0
        except OSError:
            return None

    def stop(self) -> None:
        """Signal the tailer to stop."""
        self._running = False


def expand_sources(patterns: list[str]) -> set[Path]:
    """Resolve plain paths (kept even if missing) and glob patterns (existing matches only)."""
    paths: set[Path] = set()
    for pat in patterns:
        if _GLOB_CHARS & set(pat):
            paths.update(Path(p) for p in glob.glob(pat, recursive=True) if Path(p).is_file())
        else:
            paths.add(Path(pat))
    return paths


class MultiTailer:
    """Tails every file matched by a list of paths/globs into one shared queue."""

    def __init__(
        self,
        patterns: list[str],
        queue: asyncio.Queue,
        poll_interval: float = 0.2,
        rescan_interval: float = 2.0,
    ):
        self.patterns = patterns
        self.queue = queue
        self.poll_interval = poll_interval
        self.rescan_interval = rescan_interval
        self.tailers: dict[Path, Tailer] = {}
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._initial_scan = True

    def _add(self, path: Path) -> None:
        # Files present at startup are tailed from EOF (no replay of history, idempotent
        # restarts); files discovered later are new, so they are read from the start.
        t = Tailer(path, self.queue, self.poll_interval, from_start=not self._initial_scan)
        self.tailers[path] = t
        self._tasks.append(asyncio.create_task(t.run(), name=f"tail:{path.name}"))
        logger.info("Tailing source: %s", path)

    def _rescan(self) -> None:
        for path in sorted(expand_sources(self.patterns)):
            if path not in self.tailers:
                self._add(path)
        self._initial_scan = False

    async def run(self) -> None:
        self._running = True
        try:
            while self._running:
                self._rescan()
                await asyncio.sleep(self.rescan_interval)
        finally:
            for t in self.tailers.values():
                t.stop()
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def stop(self) -> None:
        self._running = False
        for t in self.tailers.values():
            t.stop()

    @property
    def lines_read(self) -> int:
        return sum(t.lines_read for t in self.tailers.values())

    @property
    def lines_dropped(self) -> int:
        return sum(t.lines_dropped for t in self.tailers.values())

    @property
    def files(self) -> list[str]:
        return [str(p) for p in self.tailers]
