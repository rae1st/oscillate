"""Core audio management classes."""

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

import discord
from discord import FFmpegPCMAudio, PCMVolumeTransformer

from oscillate.db import DBManager, SQLiteDBManager
from oscillate.exceptions import AudioError, ConnectionError, OscillateError
from oscillate.filters.base import BaseFilter, FilterChain
from oscillate.metrics import Metrics
from oscillate.queue import AudioQueue, LoopMode
from oscillate.track import Track
from oscillate.utils.logging import get_logger
from oscillate.utils.typing import ChannelLike, FilterArgs, HookCallback

logger = get_logger(__name__)


class AudioManager:
    """
    Main audio management system for Discord bots.

    Handles multiple guild players, resource management, persistence,
    and provides a unified interface for audio operations.
    """

    def __init__(
        self,
        max_ffmpeg_procs: int = 4,
        idle_timeout: int = 300,
        autosave_interval: int = 30,
        crossfade_duration: float = 3.0,
        cache_size: int = 200,
        max_queue_size: int = 1000,
        enable_metrics: bool = True,
        log_level: str = "INFO",
    ):
        """
        Initialize audio manager.

        Args:
            max_ffmpeg_procs: Maximum concurrent FFmpeg processes
            idle_timeout: Seconds before idle disconnect
            autosave_interval: Seconds between queue saves
            crossfade_duration: Default crossfade duration
            cache_size: Maximum cached tracks
            max_queue_size: Maximum queue size per guild
            enable_metrics: Whether to collect metrics
            log_level: Logging level
        """
        self.players: Dict[int, GuildPlayer] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Configuration
        self.max_ffmpeg_procs = max_ffmpeg_procs
        self.idle_timeout = idle_timeout
        self.autosave_interval = autosave_interval
        self.crossfade_duration = crossfade_duration
        self.cache_size = cache_size
        self.max_queue_size = max_queue_size
        self.enable_metrics = enable_metrics

        # Resource management
        self._ffmpeg_sema = asyncio.Semaphore(max_ffmpeg_procs)
        self._adaptive_lock = asyncio.Lock()
        self._bitrate = 256000

        # State tracking
        self.running = False
        self._db_manager: Optional[DBManager] = None
        self._autosave_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None

        # Components
        self.metrics = Metrics() if enable_metrics else None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_order: List[str] = []

        # Event hooks
        self._hooks: Dict[str, List[HookCallback]] = {
            "track_start": [],
            "track_end": [],
            "idle": [],
            "pause": [],
            "resume": [],
            "stop": [],
            "skip": [],
            "error": [],
        }

        # Setup logging
        numeric_level = getattr(logging, log_level.upper(), logging.INFO)
        logging.getLogger("oscillate").setLevel(numeric_level)

    def get_player(self, guild: discord.Guild) -> "GuildPlayer":
        """
        Get or create a guild player.

        Args:
            guild: Discord guild

        Returns:
            GuildPlayer instance for the guild
        """
        if guild.id not in self.players:
            self.players[guild.id] = GuildPlayer(guild, self)
        return self.players[guild.id]

    def remove_player(self, guild_id: int) -> None:
        """Remove a guild player."""
        self.players.pop(guild_id, None)

    def start(self, db_manager: Optional[DBManager] = None) -> None:
        """
        Start the audio manager.

        Args:
            db_manager: Database manager for persistence
        """
        if self.running:
            return

        self.running = True
        self._db_manager = db_manager or SQLiteDBManager()
        self.loop = asyncio.get_running_loop()

        # Start background tasks
        self._autosave_task = asyncio.create_task(self._autosave_loop())
        self._idle_task = asyncio.create_task(self._idle_loop())

        logger.info(f"AudioManager started with {self.max_ffmpeg_procs} FFmpeg processes")

    async def shutdown(self) -> None:
        """Gracefully shutdown the audio manager."""
        logger.info("Shutting down AudioManager...")

        self.running = False

        # Save all guild states
        with contextlib.suppress(Exception):
            await self.save_all()

        # Cancel background tasks
        for task in [self._autosave_task, self._idle_task]:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(Exception):
                    await task

        # Stop all players
        for player in list(self.players.values()):
            with contextlib.suppress(Exception):
                await player.stop()

        self.players.clear()
        logger.info("AudioManager shutdown complete")

    async def _autosave_loop(self) -> None:
        """Background task for auto-saving guild states."""
        while self.running:
            await asyncio.sleep(self.autosave_interval)
            with contextlib.suppress(Exception):
                await self.save_all()

    async def _idle_loop(self) -> None:
        """Background task for handling idle timeouts."""
        while self.running:
            await asyncio.sleep(10)
            now = time.monotonic()

            for player in list(self.players.values()):
                if player.is_idle(now, self.idle_timeout):
                    await self._emit("idle", player.guild.id, {})
                    await player.stop()

    async def save_all(self) -> None:
        """Save state for all active guilds."""
        if not self._db_manager:
            return

        for guild_id in list(self.players.keys()):
            await self.save_guild(guild_id)

    async def save_guild(self, guild_id: int) -> None:
        """
        Save state for a specific guild.

        Args:
            guild_id: Guild ID to save
        """
        player = self.players.get(guild_id)
        if not player or not self._db_manager:
            return

        try:
            data = await player.serialize_state()
            await self._db_manager.save_queue_state(guild_id, data)
        except Exception as e:
            logger.error(f"Failed to save guild {guild_id}: {e}")
            await self._emit("error", guild_id, {"error": str(e), "operation": "save"})

    async def load_guild(self, guild: discord.Guild) -> None:
        """
        Load state for a specific guild.

        Args:
            guild: Discord guild to load
        """
        if not self._db_manager:
            return

        try:
            data = await self._db_manager.load_queue_state(guild.id)
            if data:
                player = self.get_player(guild)
                await player.deserialize_state(data)
                logger.info(f"Loaded state for guild {guild.id}")
        except Exception as e:
            logger.error(f"Failed to load guild {guild.id}: {e}")
            await self._emit("error", guild.id, {"error": str(e), "operation": "load"})

    @asynccontextmanager
    async def ffmpeg_token(self):
        """Context manager for FFmpeg process allocation."""
        await self._ffmpeg_sema.acquire()
        if self.metrics:
            self.metrics.ffmpeg_spawned += 1
        try:
            yield
        finally:
            self._ffmpeg_sema.release()

    async def transcode_args(self, bitrate: int) -> FilterArgs:
        """
        Get FFmpeg transcoding arguments.

        Args:
            bitrate: Target bitrate

        Returns:
            FFmpeg arguments dictionary
        """
        bitrate_k = int(bitrate / 1000)
        return {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
            "options": f"-vn -b:a {bitrate_k}k -threads 1",
        }

    async def adapt_bitrate(self) -> None:
        """Adapt bitrate based on current load."""
        async with self._adaptive_lock:
            if self.metrics and self.metrics.streams_active > max(1, self.max_ffmpeg_procs // 2):
                self._bitrate = 128000
            else:
                self._bitrate = 256000

    def cache_track(self, track: Track, extra: Optional[Dict[str, Any]] = None) -> None:
        """
        Cache track metadata.

        Args:
            track: Track to cache
            extra: Additional metadata
        """
        key = track.webpage_url or track.audio_url or track.title
        if key in self._cache:
            if self.metrics:
                self.metrics.cache_hit()
            return

        if self.metrics:
            self.metrics.cache_miss()

        entry = {"track": track.to_dict(), "meta": extra or {}}
        self._cache[key] = entry
        self._cache_order.append(key)

        # Trim cache if needed
        while len(self._cache_order) > self.cache_size:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)

    def on(self, event: str, callback: HookCallback) -> None:
        """
        Register event hook.

        Args:
            event: Event name
            callback: Callback function
        """
        if event in self._hooks:
            self._hooks[event].append(callback)
        else:
            raise ValueError(f"Unknown event: {event}")

    def off(self, event: str, callback: HookCallback) -> bool:
        """
        Unregister event hook.

        Args:
            event: Event name
            callback: Callback function to remove

        Returns:
            True if callback was removed
        """
        if event in self._hooks:
            try:
                self._hooks[event].remove(callback)
                return True
            except ValueError:
                pass
        return False

    async def _emit(self, event: str, guild_id: int, payload: Dict[str, Any]) -> None:
        """
        Emit event to registered hooks.

        Args:
            event: Event name
            guild_id: Guild ID
            payload: Event data
        """
        for callback in self._hooks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(guild_id, payload)
                else:
                    callback(guild_id, payload)
            except Exception as e:
                logger.exception(f"Hook error for event '{event}': {e}")

    def metrics_snapshot(self) -> Dict[str, Any]:
        """
        Get current metrics snapshot.

        Returns:
            Metrics data dictionary
        """
        if not self.metrics:
            return {}
        return self.metrics.snapshot()

    def get_active_guilds(self) -> Set[int]:
        """Get set of active guild IDs."""
        return set(self.players.keys())

    def get_total_tracks_queued(self) -> int:
        """Get total number of tracks across all guilds."""
        return sum(player.queue.size for player in self.players.values())


class GuildPlayer:
    """
    Per-guild audio player with queue management and filter support.
    """

    def __init__(self, guild: discord.Guild, manager: AudioManager):
        """
        Initialize guild player.

        Args:
            guild: Discord guild
            manager: Parent audio manager
        """
        self.guild = guild
        self.manager = manager

        # Audio components
        self.queue = AudioQueue(max_size=manager.max_queue_size)
        self.filter_chain = FilterChain()
        self.current: Optional[Track] = None

        # State tracking
        self.playing = False
        self._paused = False
        self.last_active = time.monotonic()
        self.volume = 1.0
        self.crossfade = manager.crossfade_duration

        # Playback tracking
        self._started_at: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._current_transformer: Optional[PCMVolumeTransformer] = None

        # Preloading
        self._preloaded_source: Optional[FFmpegPCMAudio] = None
        self._preloaded_track: Optional[Track] = None

        # Synchronization
        self._lock = asyncio.Lock()

    async def ensure_voice(self, channel: ChannelLike) -> None:
        """
        Ensure bot is connected to voice channel.

        Args:
            channel: Voice channel to connect to
        """
        vc = self.guild.voice_client

        if not vc:
            try:
                await channel.connect(reconnect=True)
                logger.info(f"Connected to voice in guild {self.guild.id}")
            except Exception as e:
                raise ConnectionError(f"Failed to connect to voice: {e}")
        elif vc.channel and vc.channel.id != channel.id:
            try:
                await vc.move_to(channel)
                logger.info(f"Moved to new voice channel in guild {self.guild.id}")
            except Exception as e:
                raise ConnectionError(f"Failed to move voice channel: {e}")

    async def add(self, track: Track) -> None:
        """
        Add track to queue and start playing if not already.

        Args:
            track: Track to add
        """
        await self.queue.put(track)
        self.manager.cache_track(track)
        self.manager.start()
        await self.process_queue()

    async def add_many(self, tracks: List[Track]) -> None:
        """
        Add multiple tracks to queue.

        Args:
            tracks: List of tracks to add
        """
        await self.queue.put_many(tracks)
        for track in tracks:
            self.manager.cache_track(track)
        self.manager.start()
        await self.process_queue()

    async def add_filter(self, filter_instance: BaseFilter) -> None:
        """
        Add audio filter.

        Args:
            filter_instance: Filter to add
        """
        self.filter_chain.add_filter(filter_instance)
        logger.info(f"Added filter '{filter_instance.name}' to guild {self.guild.id}")

    async def remove_filter(self, name: str) -> bool:
        """
        Remove audio filter by name.

        Args:
            name: Filter name to remove

        Returns:
            True if filter was removed
        """
        result = self.filter_chain.remove_filter(name)
        if result:
            logger.info(f"Removed filter '{name}' from guild {self.guild.id}")
        return result

    async def clear_filters(self) -> None:
        """Clear all audio filters."""
        self.filter_chain.clear_filters()
        logger.info(f"Cleared all filters from guild {self.guild.id}")

    async def set_volume(self, volume: float) -> None:
        """
        Set playback volume.

        Args:
            volume: Volume level (0.0-2.0)
        """
        volume = max(0.0, min(2.0, float(volume)))
        self.volume = volume

        if self._current_transformer:
            self._current_transformer.volume = volume

    async def skip(self) -> None:
        """Skip current track."""
        vc = self.guild.voice_client
        if vc and vc.is_playing():
            try:
                if self._current_transformer:
                    await self._fade_out(self._current_transformer, self.crossfade)
            except Exception:
                logger.exception(f"Skip fade error in guild {self.guild.id}")

            await self.manager._emit("skip", self.guild.id, {})
            vc.stop()

    async def pause(self) -> None:
        """Pause playback."""
        vc = self.guild.voice_client
        if vc and vc.is_playing() and not self._paused:
            with contextlib.suppress(Exception):
                vc.pause()

            self._paused = True
            self._paused_at = time.time()
            await self.manager._emit("pause", self.guild.id, {})

    async def resume(self) -> None:
        """Resume playback."""
        vc = self.guild.voice_client
        if vc and self._paused:
            with contextlib.suppress(Exception):
                vc.resume()

            if self._paused_at and self._started_at:
                paused_duration = time.time() - self._paused_at
                self._started_at += paused_duration

            self._paused = False
            self._paused_at = None
            await self.manager._emit("resume", self.guild.id, {})

    async def stop(self) -> None:
        """Stop playback and disconnect."""
        vc = self.guild.voice_client
        if vc:
            try:
                if self._current_transformer:
                    await self._fade_out(self._current_transformer, min(self.crossfade, 1.0))
            except Exception:
                logger.exception(f"Stop fade error in guild {self.guild.id}")

            with contextlib.suppress(Exception):
                await vc.disconnect()

        self.current = None
        await self.queue.clear()
        self.playing = False
        self._paused = False
        self._paused_at = None
        self._started_at = None

        with contextlib.suppress(Exception):
            if self.manager._db_manager:
                await self.manager._db_manager.clear_queue_state(self.guild.id)

        await self.manager._emit("stop", self.guild.id, {})
        self.manager.remove_player(self.guild.id)

    async def process_queue(self) -> None:
        """Process the next item in queue."""
        async with self._lock:
            if self.playing or self.queue.is_empty:
                return

            next_track = await self.queue.get()
            if not next_track:
                return

            self.current = next_track
            vc = self.guild.voice_client

            if not vc:
                self.current = None
                return

            preloaded = None
            if self._preloaded_track and self._preloaded_track == next_track:
                preloaded = self._preloaded_source
                self._preloaded_source = None
                self._preloaded_track = None

            await self._play_current(vc, source=preloaded)

    async def _play_current(self, vc: discord.VoiceClient, source: Optional[FFmpegPCMAudio] = None) -> None:
        """Play the current track."""
        if not self.current:
            return

        await self.manager.adapt_bitrate()

        async with self.manager.ffmpeg_token():
            error: Optional[Exception] = None

            if self.manager.metrics:
                self.manager.metrics.streams_active += 1

            try:
                args = await self.manager.transcode_args(self.manager._bitrate)

                filter_args = self.filter_chain.get_combined_args()
                if filter_args:
                    if "before_options" in filter_args:
                        before = args.get("before_options", "")
                        args["before_options"] = f"{before} {filter_args['before_options']}".strip()

                    if "options" in filter_args:
                        options = args.get("options", "")
                        args["options"] = f"{options} {filter_args['options']}".strip()

                if source is None:
                    source = await self._make_source(self.current, args)

                transformer = PCMVolumeTransformer(source, volume=self.volume)
                self._current_transformer = transformer

                def after_playing(exc: Optional[Exception]) -> None:
                    loop = self.manager.loop
                    if loop and not loop.is_closed():
                        asyncio.run_coroutine_threadsafe(self._finish_track(exc), loop)

                await self.manager._emit("track_start", self.guild.id, {"track": self.current.to_dict()})

                vc.play(transformer, after=after_playing)
                self.playing = True
                self._paused = False
                self._started_at = time.time()
                self._paused_at = None
                self.last_active = time.monotonic()

                asyncio.create_task(self._preload_next())

                while self.playing:
                    await asyncio.sleep(0.25)

                if self.manager.metrics:
                    duration = int(self.time_elapsed())
                    if duration > 0:
                        self.manager.metrics.record_played(self.guild.id, duration)

            except Exception as e:
                error = e
                logger.exception(f"Playback error in guild {self.guild.id}")
            finally:
                if self.manager.metrics:
                    self.manager.metrics.streams_active = max(0, self.manager.metrics.streams_active - 1)
                self._current_transformer = None

                if error:
                    await self._finish_track(error)

    async def _finish_track(self, exc: Optional[Exception]) -> None:
        """Handle track completion or error."""
        prev_track = self.current

        self.playing = False
        self._paused = False
        self._paused_at = None
        self._started_at = None
        self.current = None
        self.last_active = time.monotonic()

        await self.manager._emit("track_end", self.guild.id, {
            "track": prev_track.to_dict() if prev_track else None,
            "error": str(exc) if exc else None,
        })

        if prev_track and not exc:
            if self.queue.loop_mode == LoopMode.SINGLE:
                await self.queue.put(prev_track)
            elif self.queue.loop_mode == LoopMode.QUEUE:
                await self.queue.put(prev_track)

        await self.process_queue()

    async def _make_source(self, track: Track, args: FilterArgs) -> FFmpegPCMAudio:
        """
        Create FFmpeg audio source.

        Args:
            track: Track to create source for
            args: FFmpeg arguments

        Returns:
            FFmpeg audio source
        """
        return FFmpegPCMAudio(
            track.audio_url,
            executable="ffmpeg",
            before_options=args.get("before_options", ""),
            options=args.get("options", ""),
        )

    async def _preload_next(self) -> None:
        try:
            peek = None
            if hasattr(self.queue, "peek"):
                try:
                    peek = await getattr(self.queue, "peek")()
                except Exception:
                    peek = None

            if not peek:
                return

            if self._preloaded_track and self._preloaded_track == peek:
                return

            await self.manager.adapt_bitrate()
            args = await self.manager.transcode_args(self.manager._bitrate)
            filter_args = self.filter_chain.get_combined_args()
            if filter_args:
                if "before_options" in filter_args:
                    before = args.get("before_options", "")
                    args["before_options"] = f"{before} {filter_args['before_options']}".strip()
                if "options" in filter_args:
                    options = args.get("options", "")
                    args["options"] = f"{options} {filter_args['options']}".strip()

            async with self.manager.ffmpeg_token():
                src = await self._make_source(peek, args)
                self._preloaded_source = src
                self._preloaded_track = peek
        except Exception:
            self._preloaded_source = None
            self._preloaded_track = None

    async def _fade_out(self, transformer: PCMVolumeTransformer, duration: float) -> None:
        """
        Fade out audio over specified duration.

        Args:
            transformer: Audio transformer to fade
            duration: Fade duration in seconds
        """
        if not transformer or duration <= 0:
            return

        original_volume = transformer.volume
        steps = min(20, max(3, int(duration * 10)))

        for i in range(steps + 1):
            if not self.playing:
                break

            progress = i / steps
            transformer.volume = original_volume * (1.0 - progress)
            await asyncio.sleep(duration / steps)

    def time_elapsed(self) -> float:
        """
        Get elapsed playback time in seconds.

        Returns:
            Elapsed time in seconds
        """
        if not self.playing or not self._started_at:
            return 0.0

        if self._paused and self._paused_at:
            return max(0.0, self._paused_at - self._started_at)

        return max(0.0, time.time() - self._started_at)

    def is_idle(self, now: float, timeout: int) -> bool:
        """
        Check if player is idle and should be disconnected.

        Args:
            now: Current monotonic time
            timeout: Idle timeout in seconds

        Returns:
            True if player is idle
        """
        vc = self.guild.voice_client
        if not vc:
            return False

        if self.playing or self._paused or not self.queue.is_empty:
            return False

        return now - self.last_active > timeout

    async def serialize_state(self) -> Dict[str, Any]:
        """
        Serialize player state for persistence.

        Returns:
            State dictionary
        """
        queue_state = await self.queue.export_state()

        return {
            "current": self.current.to_dict() if self.current else None,
            "queue": queue_state,
            "volume": self.volume,
            "crossfade": self.crossfade,
            "filters": self.filter_chain.to_dict(),
            "last_saved": time.time(),
        }

    async def deserialize_state(self, data: Dict[str, Any]) -> None:
        """
        Deserialize player state from persistence.

        Args:
            data: State dictionary
        """
        self.volume = data.get("volume", 1.0)
        self.crossfade = data.get("crossfade", self.manager.crossfade_duration)

        queue_data = data.get("queue", {})
        if queue_data:
            await self.queue.import_state(queue_data)

        current_data = data.get("current")
        if current_data:
            current_track = Track.from_dict(current_data)
            await self.queue.add_to_front(current_track)

        logger.info(f"Restored state for guild {self.guild.id}")

    @property
    def status(self) -> Dict[str, Any]:
        """Get current player status."""
        return {
            "playing": self.playing,
            "paused": self._paused,
            "queue_size": self.queue.size,
            "current_track": self.current.to_dict() if self.current else None,
            "time_elapsed": self.time_elapsed(),
            "volume": self.volume,
            "loop_mode": self.queue.loop_mode.value,
            "shuffle": self.queue.shuffle,
            "filters_active": self.filter_chain.enabled_count,
        }
