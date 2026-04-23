#!/usr/bin/env python3
"""SPINE hotseat lock — Python helper compatible with crew-core/src/lease.rs.

Lock file shape (JSON):
    {"holder": "<identity>", "acquired": <unix_epoch_float>}

Acquire: write the JSON file (atomic via write-then-rename on the same fs).
Release: delete the file (only if we still hold it).
Zombie recovery: if the lock is held longer than `timeout` seconds, release it
and log a warning before re-acquiring.

Usage:
    from spine_lock import SpineLock

    with SpineLock("notebook-renderer"):
        # GPU-touching work ...
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = "/tmp/spine_lock.json"
DEFAULT_TIMEOUT = 300       # seconds before zombie recovery
POLL_INTERVAL = 0.5         # seconds between acquire retries


def _lock_path() -> Path:
    """Resolve the lock file path, matching lease.rs env-var precedence."""
    raw = (
        os.environ.get("NUCRU_SPINE_LOCK_FILE")
        or os.environ.get("SPINE_LOCK_FILE")
        or DEFAULT_LOCK_PATH
    )
    path = Path(raw.strip())
    # Expand ~ the same way lease.rs does
    if str(path).startswith("~"):
        path = path.expanduser()
    return path


def _read_lock(path: Path) -> dict | None:
    """Return the parsed lock body, or None if absent/unreadable."""
    try:
        raw = path.read_text()
        data = json.loads(raw)
        if isinstance(data, dict) and "holder" in data:
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def _write_lock(path: Path, holder: str) -> None:
    """Write the lock file atomically (same-dir tempfile → rename)."""
    body = json.dumps({"holder": holder, "acquired": time.time()})
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".spine_lock_", suffix=".tmp")
    try:
        os.write(fd, body.encode())
        os.close(fd)
        os.rename(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _release_lock(path: Path, holder: str) -> None:
    """Delete the lock file only if we are still the holder."""
    lock = _read_lock(path)
    if lock and lock.get("holder") == holder:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class SpineLock:
    """Context-manager SPINE hotseat lock.

    Parameters
    ----------
    holder : str
        Identity string written into the lock file (matches lease.rs ``holder``).
    timeout : float
        Seconds a foreign holder may hold the lock before zombie recovery kicks
        in. Default 300.
    poll : float
        Seconds between acquire retries while the lock is held by another.
        Default 0.5.
    """

    def __init__(
        self,
        holder: str = "notebook-renderer",
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = POLL_INTERVAL,
    ):
        self.holder = holder
        self.timeout = timeout
        self.poll = poll
        self._path = _lock_path()
        self._held = False

    # -- public API -----------------------------------------------------------

    def acquire(self) -> None:
        """Block until the lock is acquired."""
        while True:
            lock = _read_lock(self._path)
            if lock is None:
                # Available
                _write_lock(self._path, self.holder)
                self._held = True
                logger.debug("SPINE lock acquired by %s", self.holder)
                return
            if lock.get("holder") == self.holder:
                # Re-entrant
                self._held = True
                return
            # Held by someone else — check zombie timeout
            age = time.time() - float(lock.get("acquired", 0))
            if age > self.timeout:
                logger.warning(
                    "SPINE lock held by %s for %.0fs (>%ds timeout) — forcing release (zombie recovery)",
                    lock["holder"],
                    age,
                    self.timeout,
                )
                _release_lock(self._path, lock["holder"])
                continue  # retry immediately
            logger.debug(
                "SPINE lock held by %s (%.0fs), waiting…",
                lock["holder"],
                age,
            )
            time.sleep(self.poll)

    def release(self) -> None:
        """Release the lock if we hold it."""
        if self._held:
            _release_lock(self._path, self.holder)
            self._held = False
            logger.debug("SPINE lock released by %s", self.holder)

    # -- context manager ------------------------------------------------------

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False
