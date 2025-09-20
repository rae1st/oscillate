from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from oscillate.exceptions import FilterError
from oscillate.utils.typing import FilterArgs


class BaseFilter(ABC):
    """
    Abstract base class for all audio filters.
    
    All filters must implement get_ffmpeg_args to provide FFmpeg arguments.
    """

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled
        self._priority = 0

    @abstractmethod
    def get_ffmpeg_args(self) -> FilterArgs:
        """Return FFmpeg args for this filter."""
        ...

    @property
    def priority(self) -> int:
        return self._priority

    @priority.setter
    def priority(self, value: int) -> None:
        self._priority = value

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def toggle(self) -> None:
        self.enabled = not self.enabled

    def validate_params(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.__class__.__name__,
            "enabled": self.enabled,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseFilter:
        filter_instance = cls(data.get("name", "Unknown"))
        filter_instance.enabled = data.get("enabled", True)
        filter_instance.priority = data.get("priority", 0)
        return filter_instance

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"{self.name} ({status})"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', enabled={self.enabled})"


class FilterChain:
    """Manages a chain of audio filters and combines their FFmpeg arguments."""

    def __init__(self) -> None:
        self._filters: list[BaseFilter] = []

    def add_filter(self, filter_instance: BaseFilter) -> None:
        if not isinstance(filter_instance, BaseFilter):
            raise FilterError(
                f"Filter must be instance of BaseFilter, got {type(filter_instance)}"
            )

        filter_instance.validate_params()
        self.remove_filter(filter_instance.name)
        self._filters.append(filter_instance)
        self._sort_filters()

    def remove_filter(self, name: str) -> bool:
        for i, f in enumerate(self._filters):
            if f.name == name:
                self._filters.pop(i)
                return True
        return False

    def get_filter(self, name: str) -> BaseFilter | None:
        for f in self._filters:
            if f.name == name:
                return f
        return None

    def clear_filters(self) -> None:
        self._filters.clear()

    def enable_filter(self, name: str) -> bool:
        f = self.get_filter(name)
        if f:
            f.enable()
            return True
        return False

    def disable_filter(self, name: str) -> bool:
        f = self.get_filter(name)
        if f:
            f.disable()
            return True
        return False

    def toggle_filter(self, name: str) -> bool:
        f = self.get_filter(name)
        if f:
            f.toggle()
            return True
        return False

    def _sort_filters(self) -> None:
        self._filters.sort(key=lambda f: f.priority)

    def get_combined_args(self) -> FilterArgs:
        before_options: list[str] = []
        options: list[str] = []
        audio_filters: list[str] = []

        for f in self._filters:
            if not f.enabled:
                continue

            try:
                args = f.get_ffmpeg_args()
                if args.get("before_options"):
                    before_options.append(str(args["before_options"]))
                if args.get("options"):
                    options.append(str(args["options"]))
                if args.get("af"):
                    audio_filters.append(str(args["af"]))
            except Exception as e:
                raise FilterError(f"Error getting args from filter '{f.name}': {e}")

        combined: dict[str, str] = {}
        if before_options:
            combined["before_options"] = " ".join(before_options)
        if options or audio_filters:
            parts: list[str] = []
            if options:
                parts.extend(options)
            if audio_filters:
                af_string = ",".join(audio_filters)
                parts.append(f"-af {af_string}")
            combined["options"] = " ".join(parts)

        return combined

    @property
    def filter_count(self) -> int:
        return len(self._filters)

    @property
    def enabled_count(self) -> int:
        return sum(1 for f in self._filters if f.enabled)

    def get_filter_names(self) -> list[str]:
        return [f.name for f in self._filters]

    def get_enabled_filter_names(self) -> list[str]:
        return [f.name for f in self._filters if f.enabled]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filters": [f.to_dict() for f in self._filters],
            "filter_count": self.filter_count,
            "enabled_count": self.enabled_count,
        }

    def __len__(self) -> int:
        return len(self._filters)

    def __bool__(self) -> bool:
        return self.enabled_count > 0

    def __iter__(self):
        return iter(self._filters)

    def __str__(self) -> str:
        if not self._filters:
            return "FilterChain(empty)"
        enabled_names = self.get_enabled_filter_names()
        return f"FilterChain({len(enabled_names)} enabled: {', '.join(enabled_names)})"
