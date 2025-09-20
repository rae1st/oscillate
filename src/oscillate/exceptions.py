class OscillateError(Exception):
    """Base exception for all Oscillate errors."""

    def __init__(self, message: str, *args) -> None:
        super().__init__(message, *args)
        self.message = message


class AudioError(OscillateError):
    """Raised when audio playback encounters an error."""


class FilterError(OscillateError):
    """Raised when filter operations fail."""


class QueueError(OscillateError):
    """Raised when queue operations fail."""


class DBError(OscillateError):
    """Raised when database operations fail."""


class FFmpegError(AudioError):
    """Raised when FFmpeg operations fail."""


class OpusError(AudioError):
    """Raised when Opus codec operations fail."""


class ConnectionError(AudioError):
    """Raised when voice connection operations fail."""


class TrackError(OscillateError):
    """Raised when track operations fail."""


class ConfigurationError(OscillateError):
    """Raised when configuration is invalid."""


class ResourceLimitError(OscillateError):
    """Raised when resource limits are exceeded."""
