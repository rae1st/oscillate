import asyncio
import json
import sys
from pathlib import Path

import click

from oscillate import __version__, create_manager
from oscillate.db import SQLiteDBManager
from oscillate.ffmpeg import check_ffmpeg_availability, check_opus_availability
from oscillate.metrics import start_metrics_server
from oscillate.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


@click.group()
@click.version_option(version=__version__)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(verbose: bool) -> None:
    """Oscillate - Production-grade Discord audio streaming package."""
    log_level = "DEBUG" if verbose else "INFO"
    setup_logging(level=log_level)


@main.command()
@click.option("--ffmpeg-path", help="Path to FFmpeg executable")
def diagnose(ffmpeg_path: str) -> None:
    """Check system compatibility and requirements."""
    click.echo("🎵 Oscillate System Diagnostics")
    click.echo("=" * 40)

    # Python version
    python_version = sys.version_info
    click.echo(
        f"Python Version: {python_version.major}.{python_version.minor}.{python_version.micro}"
    )
    if python_version < (3, 8):
        click.echo("❌ Python 3.8+ required", err=True)
        sys.exit(1)
    click.echo("✅ Python version OK")

    # FFmpeg
    ffmpeg_available, ffmpeg_version = check_ffmpeg_availability(ffmpeg_path)
    if ffmpeg_available:
        click.echo(f"✅ FFmpeg available: {ffmpeg_version}")
    else:
        click.echo("❌ FFmpeg not found or not working")
        click.echo("   Please install FFmpeg: https://ffmpeg.org/download.html")

    # Opus
    opus_available = check_opus_availability()
    if opus_available:
        click.echo("✅ Opus codec available")
    else:
        click.echo("❌ Opus codec not available")
        click.echo("   Install with: apt-get install libopus-dev (Linux)")

    # discord.py
    try:
        import discord

        click.echo(f"✅ discord.py {discord.__version__} installed")
    except ImportError:
        click.echo("❌ discord.py not installed")
        click.echo("   Install with: pip install discord.py")

    # Summary
    if ffmpeg_available and opus_available:
        click.echo("\n🎉 All checks passed! Oscillate is ready to use.")
    else:
        click.echo("\n⚠️  Some dependencies are missing. Please install them.")
        sys.exit(1)


@main.command()
@click.option("--port", "-p", default=8000, help="Metrics server port")
@click.option("--host", "-h", default="0.0.0.0", help="Metrics server host")
def metrics_server(port: int, host: str) -> None:
    """Start Prometheus metrics server."""
    click.echo(f"Starting metrics server on {host}:{port}")
    start_metrics_server(port=port, host=host)  # non-blocking now
    click.echo("Metrics server started. Press Ctrl+C to stop.")
    try:
        asyncio.run(asyncio.Event().wait())
    except KeyboardInterrupt:
        click.echo("\nShutting down metrics server...")


@main.command()
@click.option("--db-path", default="oscillate.db", help="Database file path")
@click.option("--guild-id", type=int, help="Specific guild ID to export")
@click.option("--output", "-o", help="Output file path")
def export_data(db_path: str, guild_id: int, output: str) -> None:
    """Export guild data from database."""

    async def export():
        db = SQLiteDBManager(db_path)
        await db.initialize()
        try:
            if guild_id:
                data = await db.export_guild_data(guild_id)
                default_output = f"guild_{guild_id}_export.json"
            else:
                click.echo("❌ Guild ID export only supported currently")
                return
            output_path = output or default_output
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            click.echo(f"✅ Data exported to {output_path}")
        finally:
            await db.close()

    asyncio.run(export())


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--db-path", default="oscillate.db", help="Database file path")
def import_data(file_path: str, db_path: str) -> None:
    """Import guild data into database."""

    async def import_data_async():
        with open(file_path, "r") as f:
            data = json.load(f)
        db = SQLiteDBManager(db_path)
        await db.initialize()
        try:
            await db.import_guild_data(data)
            click.echo(f"✅ Data imported from {file_path}")
        finally:
            await db.close()

    asyncio.run(import_data_async())


@main.command()
@click.option("--db-path", default="oscillate.db", help="Database file path")
@click.option("--days", default=30, help="Days of history to keep")
def cleanup(db_path: str, days: int) -> None:
    """Clean up old database records."""

    async def cleanup_async():
        db = SQLiteDBManager(db_path)
        await db.initialize()
        try:
            deleted = await db.cleanup_old_history(days)
            click.echo(f"✅ Cleaned up {deleted} old records")
        finally:
            await db.close()

    asyncio.run(cleanup_async())


@main.command()
@click.option("--config-file", help="Configuration file path")
def test_server(config_file: str) -> None:
    """Start a test audio server."""
    click.echo("🎵 Starting Oscillate test server...")

    async def run_test_server():
        config = {}
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                config = json.load(f)

        manager = create_manager(
            max_ffmpeg_procs=2,
            idle_timeout=60,
            enable_metrics=True,
            **config,
        )

        db = SQLiteDBManager("test_oscillate.db")
        manager.start(db)

        start_metrics_server(8000)  # non-blocking
        click.echo("✅ Test server running:")
        click.echo("   - Metrics: http://localhost:8000")
        click.echo("   - Database: test_oscillate.db")
        click.echo("Press Ctrl+C to stop...")

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            click.echo("\nShutting down test server...")
            await manager.shutdown()

    asyncio.run(run_test_server())


@main.command()
@click.option("--db-path", default="oscillate.db", help="Database file path")
@click.option("--guild-id", type=int, help="Guild ID for stats")
def stats(db_path: str, guild_id: int) -> None:
    """Show statistics from database."""

    async def show_stats():
        db = SQLiteDBManager(db_path)
        await db.initialize()
        try:
            if guild_id:
                guild_stats = await db.get_guild_stats(guild_id)
                top_tracks = await db.get_top_tracks(guild_id, 10)
                click.echo(f"📊 Guild {guild_id} Statistics")
                click.echo("=" * 40)
                click.echo(f"Total Tracks Played: {guild_stats['total_tracks_played']}")
                click.echo(
                    f"Total Playtime: {guild_stats['total_playtime_seconds']} seconds"
                )
                click.echo(f"Last Activity: {guild_stats['last_activity']}")
                if guild_stats["most_active_user"]:
                    user_info = guild_stats["most_active_user"]
                    click.echo(
                        f"Most Active User: {user_info['user_id']} "
                        f"({user_info['request_count']} requests)"
                    )
                click.echo("\n🎵 Top Tracks:")
                for i, track_info in enumerate(top_tracks, 1):
                    track = track_info["track"]
                    click.echo(
                        f"{i:2d}. {track['title']} ({track_info['play_count']} plays)"
                    )
            else:
                click.echo("❌ Please specify --guild-id")
        finally:
            await db.close()

    asyncio.run(show_stats())


@main.command()
def info() -> None:
    """Show package information."""
    click.echo("🎵 Oscillate Audio Streaming Package")
    click.echo("=" * 40)
    click.echo(f"Version: {__version__}")
    click.echo("Author: rae1st")
    click.echo("GitHub: https://github.com/rae1st/oscillate")
    click.echo("License: MIT")

    click.echo("\n📦 Features:")
    features = [
        "Advanced audio filters (EQ, bass boost, nightcore, 8D audio)",
        "Smart queue management with shuffle and loop modes",
        "Prometheus metrics integration",
        "SQLite persistence with auto-save",
        "Idle timeout and resource management",
        "Production-ready error handling",
        "Full async/await support",
        "Type hints and comprehensive testing",
    ]
    for feature in features:
        click.echo(f"  ✅ {feature}")


if __name__ == "__main__":
    main()
