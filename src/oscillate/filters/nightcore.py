from __future__ import annotations

from typing import Any

from oscillate.exceptions import FilterError
from oscillate.filters.base import BaseFilter
from oscillate.utils.typing import FilterArgs


class Nightcore(BaseFilter):
    """
    Nightcore filter that modifies pitch and tempo.
    """

    NIGHTCORE_PRESETS: dict[str, tuple[float, float]] = {
        "light": (1.1, 1.05),
        "medium": (1.2, 1.15),
        "heavy": (1.35, 1.3),
        "extreme": (1.5, 1.45),
    }

    DAYCORE_PRESETS: dict[str, tuple[float, float]] = {
        "light": (0.95, 0.9),
        "medium": (0.85, 0.8),
        "heavy": (0.75, 0.7),
        "extreme": (0.65, 0.6),
    }

    def __init__(
        self,
        pitch: float = 1.2,
        tempo: float = 1.15,
        preserve_formants: bool = True,
        name: str = "nightcore",
        enabled: bool = True,
    ) -> None:
        super().__init__(name, enabled)
        self._priority = 20
        self.pitch = pitch
        self.tempo = tempo
        self.preserve_formants = preserve_formants
        self.validate_params()

    def validate_params(self) -> bool:
        if not 0.5 <= self.pitch <= 2.0:
            raise FilterError(f"Pitch {self.pitch} out of range (0.5–2.0)")
        if not 0.5 <= self.tempo <= 2.0:
            raise FilterError(f"Tempo {self.tempo} out of range (0.5–2.0)")
        return True

    def set_pitch(self, pitch: float) -> None:
        self.pitch = pitch
        self.validate_params()

    def set_tempo(self, tempo: float) -> None:
        self.tempo = tempo
        self.validate_params()

    def set_nightcore_preset(self, intensity: str = "medium") -> None:
        if intensity not in self.NIGHTCORE_PRESETS:
            raise FilterError(f"Unknown nightcore preset: {intensity}")
        self.pitch, self.tempo = self.NIGHTCORE_PRESETS[intensity]

    def set_daycore_preset(self, intensity: str = "medium") -> None:
        if intensity not in self.DAYCORE_PRESETS:
            raise FilterError(f"Unknown daycore preset: {intensity}")
        self.pitch, self.tempo = self.DAYCORE_PRESETS[intensity]

    def get_ffmpeg_args(self) -> FilterArgs:
        if not self.enabled:
            return {}

        filters: list[str] = []

        if abs(self.tempo - 1.0) > 0.01:
            filters.append(f"atempo={self.tempo}")

        if abs(self.pitch - 1.0) > 0.01:
            if self.preserve_formants:
                filters.append(f"asetrate=44100*{self.pitch},aresample=44100")
            else:
                filters.append(f"asetrate=44100*{self.pitch},aresample=44100")

        return {"af": ",".join(filters)} if filters else {}

    def get_effect_description(self) -> str:
        if self.pitch > 1.05 and self.tempo > 1.05:
            return "Nightcore (faster, higher pitch)"
        if self.pitch < 0.95 and self.tempo < 0.95:
            return "Daycore (slower, lower pitch)"
        if self.pitch > 1.05:
            return "Higher pitch"
        if self.pitch < 0.95:
            return "Lower pitch"
        if self.tempo > 1.05:
            return "Faster tempo"
        if self.tempo < 0.95:
            return "Slower tempo"
        return "No significant change"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "pitch": self.pitch,
                "tempo": self.tempo,
                "preserve_formants": self.preserve_formants,
                "effect_description": self.get_effect_description(),
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Nightcore:
        nightcore = cls(
            pitch=data.get("pitch", 1.2),
            tempo=data.get("tempo", 1.15),
            preserve_formants=data.get("preserve_formants", True),
            name=data.get("name", "nightcore"),
            enabled=data.get("enabled", True),
        )
        nightcore.priority = data.get("priority", 20)
        return nightcore

    @classmethod
    def create_nightcore(cls, intensity: str = "medium", name: str = "nightcore") -> Nightcore:
        instance = cls(name=name)
        instance.set_nightcore_preset(intensity)
        return instance

    @classmethod
    def create_daycore(cls, intensity: str = "medium", name: str = "daycore") -> Nightcore:
        instance = cls(name=name)
        instance.set_daycore_preset(intensity)
        return instance

    @classmethod
    def pitch_only(cls, pitch: float, name: str = "pitch_shift") -> Nightcore:
        return cls(pitch=pitch, tempo=1.0, name=name)

    @classmethod
    def tempo_only(cls, tempo: float, name: str = "tempo_change") -> Nightcore:
        return cls(pitch=1.0, tempo=tempo, name=name)

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"Nightcore ({self.get_effect_description()}, {status})"
