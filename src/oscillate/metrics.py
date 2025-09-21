import time
import threading
from typing import Any, Dict, Optional

from oscillate.utils.logging import get_logger

logger = get_logger(__name__)

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        start_http_server,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client not available, metrics will be basic")
    PROMETHEUS_AVAILABLE = False


class Metrics:
    """
    Metrics collection system with optional Prometheus integration.

    Tracks audio streaming metrics, performance data, and usage statistics.
    """

    def __init__(self, enable_prometheus: bool = True):
        """Initialize metrics collection."""
        self.start_time = time.time()
        self.enable_prometheus = enable_prometheus and PROMETHEUS_AVAILABLE

        # Basic counters
        self.ffmpeg_spawned = 0
        self.streams_active = 0
        self.total_played_seconds = 0
        self.per_guild_played: Dict[int, int] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.errors = 0
        self.tracks_played = 0
        self.commands_executed = 0

        # Performance tracking
        self._operation_times: Dict[str, float] = {}  # stores last duration per operation

        # Prometheus metrics
        self._prometheus_metrics: Dict[str, Any] = {}
        if self.enable_prometheus:
            self._setup_prometheus_metrics()

    def _setup_prometheus_metrics(self) -> None:
        """Setup Prometheus metrics collectors."""
        if not PROMETHEUS_AVAILABLE:
            return

        self._prometheus_metrics = {
            # Counters
            "tracks_played_total": Counter(
                "oscillate_tracks_played_total",
                "Total number of tracks played",
                ["guild_id"],
            ),
            "ffmpeg_processes_spawned_total": Counter(
                "oscillate_ffmpeg_processes_spawned_total",
                "Total number of FFmpeg processes spawned",
            ),
            "cache_operations_total": Counter(
                "oscillate_cache_operations_total",
                "Cache operations",
                ["operation"],  # hit, miss
            ),
            "errors_total": Counter(
                "oscillate_errors_total",
                "Total number of errors",
                ["error_type"],
            ),
            "commands_total": Counter(
                "oscillate_commands_total",
                "Total commands executed",
                ["command_name", "guild_id"],
            ),
            # Gauges
            "active_streams": Gauge(
                "oscillate_active_streams",
                "Number of currently active audio streams",
            ),
            "active_guilds": Gauge(
                "oscillate_active_guilds",
                "Number of guilds with active players",
            ),
            "queue_sizes": Gauge(
                "oscillate_queue_size",
                "Current queue size",
                ["guild_id"],
            ),
            "uptime_seconds": Gauge(
                "oscillate_uptime_seconds",
                "Uptime in seconds",
            ),
            # Histograms
            "track_duration_seconds": Histogram(
                "oscillate_track_duration_seconds",
                "Track duration distribution",
                buckets=[30, 60, 120, 180, 300, 600, 1200, 3600],
            ),
            "operation_duration_seconds": Histogram(
                "oscillate_operation_duration_seconds",
                "Operation duration distribution",
                ["operation"],
                buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
            ),
        }

        logger.info("Prometheus metrics initialized")

    def uptime(self) -> float:
        """Get uptime in seconds."""
        uptime_secs = time.time() - self.start_time
        if self._prometheus_metrics:
            self._prometheus_metrics["uptime_seconds"].set(uptime_secs)
        return uptime_secs

    def record_played(self, guild_id: int, seconds: int) -> None:
        """Record track played time."""
        self.total_played_seconds += seconds
        self.per_guild_played[guild_id] = (
            self.per_guild_played.get(guild_id, 0) + seconds
        )
        self.tracks_played += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["tracks_played_total"].labels(
                guild_id=str(guild_id)
            ).inc()
            self._prometheus_metrics["track_duration_seconds"].observe(seconds)

    def record_ffmpeg_spawn(self) -> None:
        """Record FFmpeg process spawn."""
        self.ffmpeg_spawned += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["ffmpeg_processes_spawned_total"].inc()

    def set_active_streams(self, count: int) -> None:
        """Set number of active streams."""
        self.streams_active = count
        if self._prometheus_metrics:
            self._prometheus_metrics["active_streams"].set(count)

    def set_active_guilds(self, count: int) -> None:
        """Set number of active guilds."""
        if self._prometheus_metrics:
            self._prometheus_metrics["active_guilds"].set(count)

    def set_guild_queue_size(self, guild_id: int, size: int) -> None:
        """Set queue size for a guild."""
        if self._prometheus_metrics:
            self._prometheus_metrics["queue_sizes"].labels(
                guild_id=str(guild_id)
            ).set(size)

    def cache_hit(self) -> None:
        """Record cache hit."""
        self.cache_hits += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["cache_operations_total"].labels(
                operation="hit"
            ).inc()

    def cache_miss(self) -> None:
        """Record cache miss."""
        self.cache_misses += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["cache_operations_total"].labels(
                operation="miss"
            ).inc()

    def record_error(self, error_type: str = "unknown") -> None:
        """Record an error occurrence."""
        self.errors += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["errors_total"].labels(
                error_type=error_type
            ).inc()

    def record_command(self, command_name: str, guild_id: int) -> None:
        """Record command execution."""
        self.commands_executed += 1
        if self._prometheus_metrics:
            self._prometheus_metrics["commands_total"].labels(
                command_name=command_name,
                guild_id=str(guild_id),
            ).inc()

    def time_operation(self, operation: str) -> "OperationTimer":
        """Context manager for timing operations."""
        return OperationTimer(self, operation)

    def record_operation_time(self, operation: str, duration: float) -> None:
        """Record operation duration (overwrites last run)."""
        self._operation_times[operation] = duration
        if self._prometheus_metrics:
            self._prometheus_metrics["operation_duration_seconds"].labels(
                operation=operation
            ).observe(duration)

    def get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate (0-100%)."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return (self.cache_hits / total) * 100

    def get_avg_track_duration(self) -> float:
        """Get average track duration in seconds."""
        if self.tracks_played == 0:
            return 0.0
        return self.total_played_seconds / self.tracks_played

    def get_guild_playtime(self, guild_id: int) -> int:
        """Get total playtime for a guild (seconds)."""
        return self.per_guild_played.get(guild_id, 0)

    def get_top_guilds_by_playtime(self, limit: int = 10) -> Dict[int, int]:
        """Get top guilds by playtime."""
        sorted_guilds = sorted(
            self.per_guild_played.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return dict(sorted_guilds[:limit])

    def reset_guild_stats(self, guild_id: int) -> None:
        """Reset statistics for a specific guild."""
        self.per_guild_played.pop(guild_id, None)
        if self._prometheus_metrics:
            self._prometheus_metrics["queue_sizes"].labels(
                guild_id=str(guild_id)
            ).set(0)

    def reset_all(self) -> None:
        """Reset all counters (useful for tests)."""
        self.ffmpeg_spawned = 0
        self.streams_active = 0
        self.total_played_seconds = 0
        self.per_guild_played.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.errors = 0
        self.tracks_played = 0
        self.commands_executed = 0
        self._operation_times.clear()
        self.start_time = time.time()
        logger.info("All metrics counters reset")

    def snapshot(self) -> Dict[str, Any]:
        """Get complete metrics snapshot as dict."""
        return {
            "uptime": self.uptime(),
            "ffmpeg_spawned": self.ffmpeg_spawned,
            "streams_active": self.streams_active,
            "total_played_seconds": self.total_played_seconds,
            "tracks_played": self.tracks_played,
            "commands_executed": self.commands_executed,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.get_cache_hit_rate(),
            "avg_track_duration": self.get_avg_track_duration(),
            "errors": self.errors,
            "per_guild_played": self.per_guild_played.copy(),
            "top_guilds": self.get_top_guilds_by_playtime(5),
            "operation_times": self._operation_times.copy(),
        }

    def export_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        if not PROMETHEUS_AVAILABLE:
            return "# Prometheus client not available\n"
        return generate_latest().decode("utf-8")


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(self, metrics: Metrics, operation: str):
        self.metrics = metrics
        self.operation = operation
        self.start_time: Optional[float] = None

    def __enter__(self) -> "OperationTimer":
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.metrics.record_operation_time(self.operation, duration)


async def start_metrics_server(
    port: int = 8000, host: str = "0.0.0.0", background: bool = True
) -> None:
    """Start Prometheus metrics HTTP server in background thread."""
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Cannot start metrics server: prometheus_client not available")
        return

    def _run():
        try:
            start_http_server(port, addr=host)
            logger.info(f"Prometheus metrics server started on {host}:{port}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")

    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()


def create_metrics(enable_prometheus: bool = True) -> Metrics:
    """Factory for Metrics instance."""
    return Metrics(enable_prometheus=enable_prometheus)
