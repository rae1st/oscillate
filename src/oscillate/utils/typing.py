from __future__ import annotations

from typing import Any, Callable, Protocol

import discord


class UserLike(Protocol):
    """Protocol for objects that can represent a Discord user."""

    id: int | None
    name: str
    display_name: str

    def __str__(self) -> str: ...


class VoiceLike(Protocol):
    """Protocol for voice-related objects."""

    def is_playing(self) -> bool: ...
    def is_paused(self) -> bool: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...


# Type aliases
FilterArgs = dict[str, Any]
TrackDict = dict[str, Any]
QueueState = dict[str, Any]
MetricsDict = dict[str, Any]
HookCallback = Callable[[int, dict[str, Any]], Any]

# Discord types
GuildLike = discord.Guild | int
ChannelLike = discord.VoiceChannel | discord.StageChannel
ClientLike = discord.Client | discord.Bot

# Audio types
AudioSource = (
    discord.AudioSource | discord.FFmpegPCMAudio | discord.PCMVolumeTransformer
)

# Database types
DBRow = dict[str, Any]
DBResult = list[DBRow]

# Filter types
FilterType = str | dict[str, Any]
FilterList = list[FilterType]
