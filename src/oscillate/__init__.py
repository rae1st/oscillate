from oscillate.core import AudioManager, GuildPlayer
from oscillate.track import Track
from oscillate.queue import AudioQueue
from oscillate.db import DBManager, SQLiteDBManager
from oscillate.metrics import Metrics
from oscillate.exceptions import (
    OscillateError,
    AudioError,
    FilterError,
    QueueError,
    DBError,
)

# Import commonly used filters
from oscillate.filters import (
    BaseFilter,
    Equalizer,
    BassBoost,
    Nightcore,
    Reverb,
    Echo,
    Audio8D,
    Karaoke,
    CustomFilter,
)

__version__ = "1.0.0"
__author__ = "rae1st"
__email__ = "dev@rae1st.com"
__license__ = "MIT"

__all__ = [
    # Core classes
    "AudioManager",
    "GuildPlayer", 
    "Track",
    "AudioQueue",
    
    # Database
    "DBManager",
    "SQLiteDBManager",
    
    # Metrics
    "Metrics",
    
    # Filters
    "BaseFilter",
    "Equalizer",
    "BassBoost", 
    "Nightcore",
    "Reverb",
    "Echo",
    "Audio8D",
    "Karaoke",
    "CustomFilter",
    
    # Exceptions
    "OscillateError",
    "AudioError",
    "FilterError", 
    "QueueError",
    "DBError",
    
    # Metadata
    "__version__",
    "__author__",
    "__email__",
    "__license__",
]


def get_version() -> str:
    """Get the current version of Oscillate."""
    return __version__


def create_manager(**kwargs) -> AudioManager:
    """
    Create a new AudioManager instance with sensible defaults.
    
    Args:
        **kwargs: Configuration options for AudioManager
        
    Returns:
        AudioManager: Configured audio manager instance
    """
    return AudioManager(**kwargs)
