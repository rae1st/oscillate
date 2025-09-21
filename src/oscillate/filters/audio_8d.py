from __future__ import annotations

from typing import Any

from oscillate.exceptions import FilterError
from oscillate.filters.base import BaseFilter
from oscillate.utils.typing import FilterArgs


class Audio8D(BaseFilter):
    """
    8D Audio effect filter that simulates circular audio movement.
    """

    PRESETS: dict[str, tuple[float, float, float, float]] = {
        "subtle": (0.4, 1.0, 0.5, 0.1),
        "normal": (0.7, 2.0, 0.7, 0.3),
        "intense": (0.9, 3.0, 0.8, 0.4),
        "hypnotic": (1.0, 4.0, 0.9, 0.5),
    }

    def __init__(
        self,
        strength: float = 0.8,
        speed: float = 2.0,
        radius: float = 0.7,
        reverb_amount: float = 0.3,
        name: str = "audio_8d",
        enabled: bool = True,
    ) -> None:
        super().__init__(name, enabled)
        self._priority = 30
        self.strength = strength
        self.speed = speed
        self.radius = radius
        self.reverb_amount = reverb_amount
        self.validate_params()

    def validate_params(self) -> bool:
        if not 0.1 <= self.strength <= 1.0:
            raise FilterError(f"Strength {self.strength} out of range (0.1–1.0)")
        if not 0.5 <= self.speed <= 5.0:
            raise FilterError(f"Speed {self.speed} out of range (0.5–5.0 Hz)")
        if not 0.1 <= self.radius <= 1.0:
            raise FilterError(f"Radius {self.radius} out of range (0.1–1.0)")
        if not 0.0 <= self.reverb_amount <= 1.0:
            raise FilterError(f"Reverb amount {self.reverb_amount} out of range (0.0–1.0)")
        return True

    def set_strength(self, strength: float) -> None:
        self.strength = strength
        self.validate_params()

    def set_speed(self, speed: float) -> None:
        self.speed = speed
        self.validate_params()

    def set_preset(self, preset: str) -> None:
        if preset not in self.PRESETS:
            raise FilterError(f"Unknown 8D preset: {preset}")
        self.strength, self.speed, self.radius, self.reverb_amount = self.PRESETS[preset]

    def get_ffmpeg_args(self) -> FilterArgs:
        if not self.enabled:
            return {}

        filters: list[str] = []

        # Circular panning with LFO
        depth = self.strength * self.radius
        filters.append(f"apulsator=hz={self.speed}:amount={depth*0.5}")

        # Stereo width
        filters.append(f"extrastereo=m={self.strength*2:.2f}")

        # Phase shift
        phase_shift = max(1, int(self.radius * 10))
        filters.append(
            f"aphaser=in_gain=0.4:out_gain=0.74:delay={phase_shift}:decay=0.4:speed={self.speed}"
        )

        # Reverb (subtle)
        if self.reverb_amount > 0.01:
            reverb_mix = min(0.5, self.reverb_amount)
            delay = int(50 * self.reverb_amount)
            filters.append(f"aecho=0.8:0.9:{delay}:{reverb_mix}")

        # Subtle chorus for width
        filters.append("chorus=0.5:0.9:50:0.4:0.25:2")

        return {"af": ",".join(filters)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "strength": self.strength,
                "speed": self.speed,
                "radius": self.radius,
                "reverb_amount": self.reverb_amount,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Audio8D:
        audio_8d = cls(
            strength=data.get("strength", 0.8),
            speed=data.get("speed", 2.0),
            radius=data.get("radius", 0.7),
            reverb_amount=data.get("reverb_amount", 0.3),
            name=data.get("name", "audio_8d"),
            enabled=data.get("enabled", True),
        )
        audio_8d.priority = data.get("priority", 30)
        return audio_8d

    @classmethod
    def create_preset(cls, preset: str, name: str = "audio_8d") -> Audio8D:
        instance = cls(name=name)
        instance.set_preset(preset)
        return instance

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"8D Audio (strength={self.strength:.1f}, speed={self.speed:.1f}Hz, {status})"
