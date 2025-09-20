from __future__ import annotations

from typing import Any

from oscillate.exceptions import FilterError
from oscillate.filters.base import BaseFilter
from oscillate.utils.typing import FilterArgs


class Equalizer(BaseFilter):
    """
    Multi-band equalizer filter.

    Provides control over multiple frequency bands to shape the audio spectrum.
    """

    STANDARD_BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    def __init__(
        self,
        bands: list[float] | dict[int, float],
        name: str = "equalizer",
        enabled: bool = True,
    ) -> None:
        super().__init__(name, enabled)
        self._priority = 10

        if isinstance(bands, dict):
            self._frequency_gains = dict(bands)
        else:
            if len(bands) > len(self.STANDARD_BANDS):
                raise FilterError(f"Too many bands provided (max {len(self.STANDARD_BANDS)})")
            self._frequency_gains = {
                self.STANDARD_BANDS[i]: gain for i, gain in enumerate(bands)
            }

        self.validate_params()

    def validate_params(self) -> bool:
        for freq, gain in self._frequency_gains.items():
            if not isinstance(freq, (int, float)) or freq <= 0:
                raise FilterError(f"Invalid frequency: {freq}")
            if not isinstance(gain, (int, float)):
                raise FilterError(f"Invalid gain value: {gain}")
            if gain < -20.0 or gain > 20.0:
                raise FilterError(f"Gain {gain} dB out of range (-20 to +20 dB)")
        return True

    def set_band(self, frequency: int, gain: float) -> None:
        self._frequency_gains[frequency] = gain
        self.validate_params()

    def get_band(self, frequency: int) -> float:
        return self._frequency_gains.get(frequency, 0.0)

    def reset_band(self, frequency: int) -> None:
        self._frequency_gains[frequency] = 0.0

    def reset_all_bands(self) -> None:
        for freq in self._frequency_gains:
            self._frequency_gains[freq] = 0.0

    def apply_preset(self, preset_name: str) -> None:
        presets = self.get_presets()
        if preset_name not in presets:
            raise FilterError(f"Unknown preset: {preset_name}")
        self._frequency_gains = {
            self.STANDARD_BANDS[i]: gain for i, gain in enumerate(presets[preset_name])
        }

    @classmethod
    def get_presets(cls) -> dict[str, list[float]]:
        return {
            "flat": [0.0] * 10,
            "rock": [0.5, 0.3, -0.5, -0.8, -0.3, 0.4, 0.9, 1.1, 1.1, 1.1],
            "pop": [-0.2, -0.1, 0.0, 0.2, 0.5, 0.7, 0.7, 0.5, 0.0, -0.2],
            "jazz": [0.4, 0.2, 0.1, 0.2, -0.2, -0.2, 0.0, 0.1, 0.3, 0.5],
            "classical": [0.5, 0.3, 0.2, 0.0, -0.2, -0.2, 0.0, 0.2, 0.3, 0.4],
            "electronic": [0.8, 0.5, 0.0, -0.5, -0.2, 0.0, 0.3, 0.8, 1.0, 1.2],
            "vocal": [-0.5, -0.3, -0.2, 0.1, 0.4, 0.6, 0.6, 0.4, 0.1, -0.1],
            "bass_boost": [1.2, 1.0, 0.8, 0.5, 0.0, -0.2, -0.3, -0.2, 0.0, 0.2],
            "treble_boost": [-0.2, 0.0, 0.2, 0.3, 0.5, 0.8, 1.0, 1.2, 1.4, 1.6],
        }

    def get_ffmpeg_args(self) -> FilterArgs:
        if not self.enabled or not self._frequency_gains:
            return {}
        eq_filters = [
            f"equalizer=f={freq}:width_type=o:width=1:g={gain}"
            for freq, gain in sorted(self._frequency_gains.items())
            if abs(gain) > 0.01
        ]
        return {"af": ",".join(eq_filters)} if eq_filters else {}

    @property
    def bands(self) -> dict[int, float]:
        return self._frequency_gains.copy()

    @property
    def active_bands(self) -> dict[int, float]:
        return {f: g for f, g in self._frequency_gains.items() if abs(g) > 0.01}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"bands": self._frequency_gains.copy(), "active_bands_count": len(self.active_bands)})
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Equalizer:
        bands = data.get("bands", {})
        int_bands = {int(k): v for k, v in bands.items()}
        eq = cls(bands=int_bands, name=data.get("name", "equalizer"), enabled=data.get("enabled", True))
        eq.priority = data.get("priority", 10)
        return eq

    @classmethod
    def create_preset(cls, preset_name: str, name: str = "equalizer") -> Equalizer:
        eq = cls(bands=[], name=name)
        eq.apply_preset(preset_name)
        return eq

    def __str__(self) -> str:
        active, total = len(self.active_bands), len(self._frequency_gains)
        status = "enabled" if self.enabled else "disabled"
        return f"Equalizer ({active}/{total} bands active, {status})"
