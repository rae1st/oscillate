from __future__ import annotations

from typing import Any

from oscillate.exceptions import FilterError
from oscillate.filters.base import BaseFilter
from oscillate.utils.typing import FilterArgs


class BassBoost(BaseFilter):
    """
    Bass boost filter for enhanced low-frequency response.
    
    Provides configurable bass enhancement with frequency and gain control.
    """

    def __init__(
        self,
        level: float = 5.0,
        frequency: int = 100,
        bandwidth: float = 2.0,
        name: str = "bass_boost",
        enabled: bool = True,
    ) -> None:
        super().__init__(name, enabled)
        self._priority = 15

        self.level = level
        self.frequency = frequency
        self.bandwidth = bandwidth

        self.validate_params()

    def validate_params(self) -> bool:
        if not 0.0 <= self.level <= 20.0:
            raise FilterError(f"Bass level {self.level} out of range (0-20 dB)")
        if not 20 <= self.frequency <= 200:
            raise FilterError(f"Bass frequency {self.frequency} out of range (20-200 Hz)")
        if not 0.1 <= self.bandwidth <= 5.0:
            raise FilterError(
                f"Bass bandwidth {self.bandwidth} out of range (0.1-5.0 octaves)"
            )
        return True

    def set_level(self, level: float) -> None:
        self.level = level
        self.validate_params()

    def set_frequency(self, frequency: int) -> None:
        self.frequency = frequency
        self.validate_params()

    def set_bandwidth(self, bandwidth: float) -> None:
        self.bandwidth = bandwidth
        self.validate_params()

    def get_ffmpeg_args(self) -> FilterArgs:
        if not self.enabled or self.level <= 0.01:
            return {}
        af_string = f"bass=g={self.level}:f={self.frequency}:w={self.bandwidth}"
        return {"af": af_string}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "level": self.level,
                "frequency": self.frequency,
                "bandwidth": self.bandwidth,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BassBoost:
        bass = cls(
            level=data.get("level", 5.0),
            frequency=data.get("frequency", 100),
            bandwidth=data.get("bandwidth", 2.0),
            name=data.get("name", "bass_boost"),
            enabled=data.get("enabled", True),
        )
        bass.priority = data.get("priority", 15)
        return bass

    @classmethod
    def light(cls, name: str = "bass_boost_light") -> BassBoost:
        return cls(level=3.0, frequency=80, bandwidth=1.5, name=name)

    @classmethod
    def medium(cls, name: str = "bass_boost_medium") -> BassBoost:
        return cls(level=6.0, frequency=100, bandwidth=2.0, name=name)

    @classmethod
    def heavy(cls, name: str = "bass_boost_heavy") -> BassBoost:
        return cls(level=10.0, frequency=120, bandwidth=2.5, name=name)

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"BassBoost ({self.level}dB @ {self.frequency}Hz, {status})"
