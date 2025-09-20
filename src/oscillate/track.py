from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import discord

from oscillate.utils.typing import UserLike


@dataclass
class Track:
    """
    Represents an audio track with metadata.
    
    This class holds all information about a track including its audio URL,
    metadata, and playback information.
    """

    title: str
    audio_url: str
    webpage_url: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    thumbnail: Optional[str] = None
    requester: Optional[UserLike] = None
    added_at: float = field(default_factory=time.time)
    play_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and normalize track data after initialization."""
        if not self.title:
            self.title = "Unknown Track"
        if not self.audio_url:
            raise ValueError("audio_url is required")

        if self.duration is not None and self.duration <= 0:
            self.duration = None

    @property
    def display_title(self) -> str:
        """Get a formatted display title for the track."""
        if self.uploader:
            return f"{self.title} - {self.uploader}"
        return self.title

    @property
    def formatted_duration(self) -> str:
        """Get a human-readable duration string."""
        if not self.duration:
            return "Unknown"

        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def requester_name(self) -> str:
        """Get the name of the user who requested this track."""
        if not self.requester:
            return "Unknown"

        if hasattr(self.requester, "display_name"):
            return self.requester.display_name
        if hasattr(self.requester, "name"):
            return self.requester.name
        return str(self.requester)

    @property
    def requester_id(self) -> Optional[int]:
        """Get the ID of the user who requested this track."""
        if not self.requester:
            return None

        if hasattr(self.requester, "id"):
            return self.requester.id
        return None

    def increment_play_count(self) -> None:
        """Increment the play count for this track."""
        self.play_count += 1

    def to_dict(self) -> dict[str, Any]:
        """
        Convert track to dictionary for serialization.
        
        Returns:
            Dict containing track data
        """
        return {
            "title": self.title,
            "audio_url": self.audio_url,
            "webpage_url": self.webpage_url,
            "duration": self.duration,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
            "requester_id": self.requester_id,
            "requester_name": self.requester_name,
            "added_at": self.added_at,
            "play_count": self.play_count,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], bot: Optional[discord.Client] = None
    ) -> Track:
        """
        Create track from dictionary data.
        
        Args:
            data: Dictionary containing track data
            bot: Discord bot instance for resolving requester
            
        Returns:
            Track instance
        """
        requester = None
        if bot and data.get("requester_id"):
            try:
                requester = bot.get_user(data["requester_id"])
            except Exception:
                requester = None

        if not requester and data.get("requester_name"):

            class SimpleRequester:
                def __init__(self, name: str, user_id: Optional[int] = None):
                    self.name = name
                    self.display_name = name
                    self.id = user_id

                def __str__(self) -> str:
                    return self.name

            requester = SimpleRequester(
                data["requester_name"], data.get("requester_id")
            )

        return cls(
            title=data["title"],
            audio_url=data["audio_url"],
            webpage_url=data.get("webpage_url"),
            duration=data.get("duration"),
            uploader=data.get("uploader"),
            thumbnail=data.get("thumbnail"),
            requester=requester,
            added_at=data.get("added_at", time.time()),
            play_count=data.get("play_count", 0),
            metadata=copy.deepcopy(data.get("metadata", {})),
        )

    def clone(self) -> Track:
        """
        Create a deep copy of this track.
        
        Returns:
            New Track instance with the same data
        """
        return Track(
            title=self.title,
            audio_url=self.audio_url,
            webpage_url=self.webpage_url,
            duration=self.duration,
            uploader=self.uploader,
            thumbnail=self.thumbnail,
            requester=self.requester,
            added_at=self.added_at,
            play_count=self.play_count,
            metadata=copy.deepcopy(self.metadata),
        )

    def __str__(self) -> str:
        """String representation of the track."""
        return self.display_title

    def __repr__(self) -> str:
        """Developer-friendly representation of the track."""
        return (
            f"Track(title='{self.title}', uploader='{self.uploader}', "
            f"duration={self.duration}, requester='{self.requester_name}')"
        )

    def __eq__(self, other: object) -> bool:
        """Check equality based on audio URL."""
        if not isinstance(other, Track):
            return NotImplemented
        return self.audio_url == other.audio_url

    def __hash__(self) -> int:
        """Hash based on audio URL for use in sets/dicts."""
        return hash(self.audio_url)
