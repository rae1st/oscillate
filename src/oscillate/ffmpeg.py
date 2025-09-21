import contextlib
import json
import shutil
import subprocess
from typing import Optional, Tuple

import discord

from oscillate.exceptions import FFmpegError, OpusError
from oscillate.utils.logging import get_logger

logger = get_logger(__name__)


def load_opus() -> None:
    """Load Opus codec for Discord audio."""
    try:
        if not discord.opus.is_loaded():
            opus_paths = [
                "libopus.so",
                "/usr/lib/x86_64-linux-gnu/libopus.so",
                "/usr/lib/libopus.so.0",
                "/run/current-system/sw/lib/libopus.so",
                "/opt/homebrew/lib/libopus.dylib",
                "/usr/local/lib/libopus.dylib",
            ]
            for path in opus_paths:
                try:
                    discord.opus.load_opus(path)
                    logger.info(f"Loaded Opus from: {path}")
                    break
                except Exception:
                    continue
            if not discord.opus.is_loaded():
                raise OpusError("Failed to load Opus codec from any known path")
    except Exception as e:
        logger.warning(f"Failed to load Opus codec: {e}")
        raise OpusError(f"Opus codec loading failed: {e}")


def check_ffmpeg_availability(ffmpeg_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Check if FFmpeg is available and return version."""
    executable = ffmpeg_path or "ffmpeg"
    try:
        if not shutil.which(executable):
            return False, None
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, None
        version_line = next(
            (line for line in result.stdout.splitlines() if line.startswith("ffmpeg version")),
            None,
        )
        if version_line:
            parts = version_line.split()
            version = parts[2] if len(parts) > 2 else "unknown"
            return True, version
        return True, "unknown"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return False, None
    except Exception as e:
        logger.warning(f"Error checking FFmpeg: {e}")
        return False, None


def check_opus_availability() -> bool:
    """Return True if Opus codec is available."""
    try:
        load_opus()
        return discord.opus.is_loaded()
    except Exception:
        return False


def get_ffmpeg_executable() -> str:
    """Return FFmpeg executable path, or raise if missing."""
    executable = "ffmpeg"
    if not shutil.which(executable):
        raise FFmpegError("FFmpeg executable not found in PATH")
    return executable


def validate_ffmpeg_args(args: dict) -> dict:
    """Validate and sanitize FFmpeg arguments."""
    validated = {}
    before_options = args.get("before_options", "")
    if before_options:
        dangerous = ["-f null", "-y /", "rm ", "del ", ";", "&", "|", "$(", "`"]
        lowered = before_options.lower()
        for pattern in dangerous:
            if pattern in lowered:
                logger.warning(f"Removed dangerous pattern from before_options: {pattern}")
                before_options = before_options.replace(pattern, "")
        validated["before_options"] = before_options.strip()
    options = args.get("options", "")
    if options:
        if "-vn" not in options:
            options = f"-vn {options}"
        validated["options"] = options.strip()
    return validated


def build_ffmpeg_command(input_url: str, args: dict, executable: Optional[str] = None) -> list:
    """Build FFmpeg command list for Discord streaming."""
    cmd = [executable or get_ffmpeg_executable()]
    before_options = args.get("before_options", "")
    if before_options:
        cmd.extend(before_options.split())
    cmd.extend(["-i", input_url])
    options = args.get("options", "")
    if options:
        cmd.extend(options.split())
    cmd.extend(["-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1"])
    return cmd


def test_ffmpeg_functionality(ffmpeg_path: Optional[str] = None) -> bool:
    """Run a minimal FFmpeg test pipeline and return True if it works."""
    executable = ffmpeg_path or "ffmpeg"
    try:
        result = subprocess.run(
            [
                executable,
                "-f",
                "lavfi",
                "-i",
                "testsrc2=duration=1:size=320x240:rate=30",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return False
    except Exception as e:
        logger.warning(f"Error testing FFmpeg: {e}")
        return False


def get_audio_info(file_path: str, ffmpeg_path: Optional[str] = None) -> dict:
    """Return audio metadata using FFprobe."""
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe") if ffmpeg_path else "ffprobe"
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        info = {"duration": None, "bitrate": None, "sample_rate": None, "channels": None, "codec": None}
        if "format" in data:
            fmt = data["format"]
            try:
                info["duration"] = float(fmt.get("duration", 0) or 0)
            except (ValueError, TypeError):
                info["duration"] = 0.0
            try:
                info["bitrate"] = int(fmt.get("bit_rate", 0) or 0)
            except (ValueError, TypeError):
                info["bitrate"] = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                try:
                    info["sample_rate"] = int(stream.get("sample_rate", 0) or 0)
                except (ValueError, TypeError):
                    info["sample_rate"] = 0
                info["channels"] = int(stream.get("channels", 0) or 0)
                info["codec"] = stream.get("codec_name")
                break
        return info
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return {}
    except Exception as e:
        logger.warning(f"Error getting audio info: {e}")
        return {}


class FFmpegProcess:
    """Wrapper for FFmpeg subprocess management."""

    def __init__(self, command: list):
        self.command = command
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """Start the FFmpeg process."""
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # avoid deadlocks
                stdin=subprocess.DEVNULL,
            )
        except Exception as e:
            raise FFmpegError(f"Failed to start FFmpeg process: {e}")

    def stop(self) -> None:
        """Stop the FFmpeg process."""
        if self.process:
            with contextlib.suppress(Exception):
                self.process.terminate()
                self.process.wait(timeout=5)
            if self.process.poll() is None:
                with contextlib.suppress(Exception):
                    self.process.kill()
                    self.process.wait(timeout=2)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def get_return_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


try:
    load_opus()
except Exception as e:
    logger.warning(f"Failed to load Opus on import: {e}")
