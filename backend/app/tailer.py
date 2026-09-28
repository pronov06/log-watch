"""
Async file tailer — reads new lines from a growing log file.

Features:
- Offset-based polling (no inotify dependency, works cross-platform)
- Truncation detection: if file size < offset, reset to 0
- Rotation detection: if file inode changes, reopen from 0 (Unix) or size shrinks (Windows)
- Partial-line buffering: holds back the last line if it doesn't end with \\n
- Bounded asyncio.Queue output: drops oldest lines with a counter if the consumer lags
- If the file doesn't exist yet, waits and retries (doesn't crash)
- Reads in chunks (up to 1 MB per poll) to avoid blocking the event loop
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 1_048_576  # 1 MB per poll cycle


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
        self._partial: str = ""
        self._running: bool = False
        self.lines_read: int = 0
        self.lines_dropped: int = 0

    async def run(self) -> None:
        """Main loop — poll the file for new data."""
        self._running = True
        logger.info("Tailer starting: %s (from_start=%s)", self.path, self.from_start)

        # Wait for the file to exist
        while self._running and not self.path.exists():
            logger.debug("Waiting for %s to appear...", self.path)
            await asyncio.sleep(self.poll_interval * 5)

        # Initial seek position
        if not self.from_start:
            try:
                self._offset = self.path.stat().st_size
            except OSError:
                self._offset = 0

        self._inode = self._get_inode()
        logger.info("Tailer ready at offset %d", self._offset)

        while self._running:
            try:
                await self._poll_once()
            except Exception as exc:
                logger.error("Tailer error (will retry): %s", exc)
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        """One poll cycle: stat, detect rotation/truncation, read new data."""
        if not self.path.exists():
            return

        try:
            stat = self.path.stat()
        except OSError:
            return

        current_inode = self._get_inode()
        file_size = stat.st_size

        # Detect rotation (inode changed) or truncation (size shrunk)
        if current_inode != self._inode or file_size < self._offset:
            action = "rotated" if current_inode != self._inode else "truncated"
            logger.info("File %s (inode: %s→%s, size: %d), resetting to 0",
                        action, self._inode, current_inode, file_size)
            self._offset = 0
            self._inode = current_inode
            self._partial = ""

        if file_size <= self._offset:
            return  # No new data

        # Read new data in a thread to avoid blocking the event loop
        data = await asyncio.to_thread(self._read_chunk, file_size)
        if not data:
            return

        # Prepend any partial line from last read
        text = self._partial + data
        self._partial = ""

        # Split into lines
        lines = text.split("\n")

        # If the last element isn't terminated by \n, it's a partial line — hold it back
        if not text.endswith("\n"):
            self._partial = lines.pop()
        else:
            # Remove the empty string after the trailing \n
            if lines and lines[-1] == "":
                lines.pop()

        # Push complete lines to the queue
        for line in lines:
            if not line:
                continue
            self.lines_read += 1
            try:
                self.queue.put_nowait(line)
            except asyncio.QueueFull:
                # Drop oldest to make room
                try:
                    self.queue.get_nowait()
                    self.lines_dropped += 1
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.queue.put_nowait(line)
                except asyncio.QueueFull:
                    self.lines_dropped += 1

    def _read_chunk(self, file_size: int) -> str:
        """Read up to MAX_CHUNK_BYTES of new data from the file (runs in a thread)."""
        bytes_to_read = min(file_size - self._offset, MAX_CHUNK_BYTES)
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                data = f.read(bytes_to_read)
                self._offset = f.tell()
                return data
        except OSError as exc:
            logger.warning("Read error: %s", exc)
            return ""

    def _get_inode(self) -> int | None:
        """Get file inode (Unix) or 0 (Windows, where inodes aren't reliable)."""
        try:
            stat = self.path.stat()
            # On Windows, st_ino is often 0 or unreliable
            return getattr(stat, "st_ino", 0) or 0
        except OSError:
            return None

    def stop(self) -> None:
        """Signal the tailer to stop."""
        self._running = False
        logger.info("Tailer stopping")
