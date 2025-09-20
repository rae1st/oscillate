from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from enum import Enum
from typing import Any, Deque, Iterable, Optional

from oscillate.exceptions import QueueError
from oscillate.track import Track


class LoopMode(Enum):
    """Loop mode enumeration."""

    NONE = "none"
    SINGLE = "single"
    QUEUE = "queue"


class AudioQueue:
    """
    Advanced audio queue with shuffle, loop modes, and history tracking.
    
    Features:
    - Loop modes: none, single track, whole queue
    - Shuffle mode with proper randomization
    - History tracking of played tracks
    - Size limits and overflow handling
    - Thread-safe operations
    """

    def __init__(
        self,
        max_size: int = 1000,
        history_size: int = 50,
        shuffle: bool = False,
        loop_mode: LoopMode = LoopMode.NONE,
    ):
        self._queue: asyncio.Queue[Track] = asyncio.Queue()
        self._history: Deque[Track] = deque(maxlen=history_size)
        self._shuffle_indices: list[int] = []
        self._shuffle_position: int = 0
        self._lock = asyncio.Lock()

        self.max_size = max_size
        self.history_size = history_size
        self.shuffle = shuffle
        self.loop_mode = loop_mode

        self._total_added = 0
        self._total_played = 0

    async def put(self, track: Track) -> None:
        async with self._lock:
            if self.size >= self.max_size:
                raise QueueError(f"Queue is full (max {self.max_size} tracks)")

            await self._queue.put(track)
            self._total_added += 1

            if self.shuffle:
                self._regenerate_shuffle_indices()

    async def put_many(self, tracks: Iterable[Track]) -> None:
        track_list = list(tracks)
        async with self._lock:
            if self.size + len(track_list) > self.max_size:
                raise QueueError(
                    f"Cannot add {len(track_list)} tracks, would exceed limit "
                    f"({self.size + len(track_list)} > {self.max_size})"
                )

            for track in track_list:
                await self._queue.put(track)
                self._total_added += 1

            if self.shuffle:
                self._regenerate_shuffle_indices()

    async def get(self) -> Optional[Track]:
        async with self._lock:
            if self._queue.empty():
                return None

            if self.shuffle:
                track = await self._get_shuffled()
            else:
                track = await self._queue.get()

            if track:
                self._add_to_history(track)
                self._total_played += 1
                if self.loop_mode == LoopMode.SINGLE:
                    # put track back immediately
                    await self._queue.put(track)
            return track

    async def _get_shuffled(self) -> Optional[Track]:
        if not self._shuffle_indices:
            self._regenerate_shuffle_indices()

        if self._shuffle_position >= len(self._shuffle_indices):
            if self.loop_mode == LoopMode.QUEUE:
                self._shuffle_position = 0
                self._regenerate_shuffle_indices()
            else:
                return None

        queue_list = list(self._queue._queue)
        if not queue_list:
            return None

        idx = self._shuffle_indices[self._shuffle_position]
        if idx >= len(queue_list):
            return None

        track = queue_list[idx]
        try:
            self._queue._queue.remove(track)
        except ValueError:
            return None

        self._shuffle_position += 1
        return track

    def _regenerate_shuffle_indices(self) -> None:
        queue_size = self._queue.qsize()
        self._shuffle_indices = list(range(queue_size))
        random.shuffle(self._shuffle_indices)
        self._shuffle_position = 0

    def _add_to_history(self, track: Track) -> None:
        track.increment_play_count()
        self._history.append(track)

    async def peek(self, count: int = 1) -> list[Track]:
        async with self._lock:
            queue_list = list(self._queue._queue)

            if self.shuffle and self._shuffle_indices:
                result: list[Track] = []
                for i in range(
                    min(count, len(self._shuffle_indices) - self._shuffle_position)
                ):
                    idx = self._shuffle_indices[self._shuffle_position + i]
                    if idx < len(queue_list):
                        result.append(queue_list[idx])
                return result
            return queue_list[:count]

    async def remove_at(self, index: int) -> Track:
        async with self._lock:
            queue_list = list(self._queue._queue)

            if index < 0:
                index += len(queue_list)
            if not 0 <= index < len(queue_list):
                raise QueueError(f"Index {index} out of range")

            track = queue_list[index]
            try:
                self._queue._queue.remove(track)
            except ValueError:
                raise QueueError("Track not found in queue")

            if self.shuffle:
                self._regenerate_shuffle_indices()
            return track

    async def move(self, src: int, dst: int) -> None:
        async with self._lock:
            queue_list = list(self._queue._queue)

            if src < 0:
                src += len(queue_list)
            if dst < 0:
                dst += len(queue_list)

            if not 0 <= src < len(queue_list):
                raise QueueError(f"Source index {src} out of range")
            if not 0 <= dst <= len(queue_list):
                raise QueueError(f"Destination index {dst} out of range")

            track = queue_list.pop(src)
            queue_list.insert(dst, track)

            self._queue = asyncio.Queue()
            for t in queue_list:
                await self._queue.put(t)

            if self.shuffle:
                self._regenerate_shuffle_indices()

    async def clear(self) -> None:
        async with self._lock:
            self._queue = asyncio.Queue()
            self._shuffle_indices.clear()
            self._shuffle_position = 0

    async def set_shuffle(self, enabled: bool) -> None:
        async with self._lock:
            self.shuffle = enabled
            if enabled:
                self._regenerate_shuffle_indices()
            else:
                self._shuffle_indices.clear()
                self._shuffle_position = 0

    def set_loop_mode(self, mode: LoopMode) -> None:
        self.loop_mode = mode

    async def get_history(self, count: Optional[int] = None) -> list[Track]:
        history_list = list(reversed(self._history))
        if count is not None:
            return history_list[:count]
        return history_list

    async def add_to_front(self, track: Track) -> None:
        async with self._lock:
            if self.size >= self.max_size:
                raise QueueError(f"Queue is full (max {self.max_size} tracks)")

            queue_list = list(self._queue._queue)
            queue_list.insert(0, track)

            self._queue = asyncio.Queue()
            for t in queue_list:
                await self._queue.put(t)

            self._total_added += 1

            if self.shuffle:
                self._regenerate_shuffle_indices()

    async def duplicate_track(self, index: int) -> None:
        async with self._lock:
            queue_list = list(self._queue._queue)

            if index < 0:
                index += len(queue_list)
            if not 0 <= index < len(queue_list):
                raise QueueError(f"Index {index} out of range")

            if self.size >= self.max_size:
                raise QueueError(f"Queue is full (max {self.max_size} tracks)")

            track_to_duplicate = queue_list[index].clone()
            queue_list.insert(index + 1, track_to_duplicate)

            self._queue = asyncio.Queue()
            for t in queue_list:
                await self._queue.put(t)

            self._total_added += 1

            if self.shuffle:
                self._regenerate_shuffle_indices()

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        return self._queue.empty()

    @property
    def is_full(self) -> bool:
        return self.size >= self.max_size

    @property
    def total_duration(self) -> Optional[int]:
        total = 0
        has_duration = False

        for track in list(self._queue._queue):
            if track.duration is not None:
                total += track.duration
                has_duration = True
            else:
                return None
        return total if has_duration else None

    @property
    def statistics(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self.max_size,
            "is_empty": self.is_empty,
            "is_full": self.is_full,
            "shuffle": self.shuffle,
            "loop_mode": self.loop_mode.value,
            "history_size": len(self._history),
            "total_added": self._total_added,
            "total_played": self._total_played,
            "total_duration": self.total_duration,
        }

    async def to_list(self) -> list[Track]:
        return list(self._queue._queue)

    async def export_state(self) -> dict[str, Any]:
        async with self._lock:
            queue_list = await self.to_list()
            history_list = list(self._history)

            return {
                "tracks": [track.to_dict() for track in queue_list],
                "history": [track.to_dict() for track in history_list],
                "shuffle": self.shuffle,
                "loop_mode": self.loop_mode.value,
                "shuffle_indices": self._shuffle_indices.copy(),
                "shuffle_position": self._shuffle_position,
                "total_added": self._total_added,
                "total_played": self._total_played,
                "timestamp": time.time(),
            }

    async def import_state(self, state: dict[str, Any]) -> None:
        async with self._lock:
            await self.clear()

            tracks = [
                Track.from_dict(track_data) for track_data in state.get("tracks", [])
            ]
            for track in tracks:
                await self._queue.put(track)

            self._history.clear()
            for track_data in state.get("history", []):
                track = Track.from_dict(track_data)
                self._history.append(track)

            self.shuffle = state.get("shuffle", False)
            self.loop_mode = LoopMode(state.get("loop_mode", "none"))
            self._shuffle_indices = state.get("shuffle_indices", [])
            self._shuffle_position = state.get("shuffle_position", 0)
            self._total_added = state.get("total_added", 0)
            self._total_played = state.get("total_played", 0)

            if self.shuffle and not self._shuffle_indices:
                self._regenerate_shuffle_indices()
