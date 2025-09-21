import logging
import sys
from typing import Optional


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(f"oscillate.{name}")


def setup_logging(
    level: str = "INFO",
    format_string: Optional[str] = None,
    enable_colors: bool = True,
) -> None:
    """
    Setup logging configuration for Oscillate.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        format_string: Custom format string
        enable_colors: Whether to enable colored output
    """
    if format_string is None:
        format_string = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"

    logger = logging.getLogger("oscillate")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    if enable_colors and sys.stdout.isatty():
        formatter = ColoredFormatter(format_string)
    else:
        formatter = logging.Formatter(format_string)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Prevent duplicate logs on root logger
    logger.propagate = False


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors without mutating original record."""
        levelname = record.levelname
        log_color = self.COLORS.get(levelname, "")
        record_copy = logging.makeLogRecord(record.__dict__.copy())
        record_copy.levelname = f"{log_color}{levelname}{self.RESET}"
        return super().format(record_copy)
