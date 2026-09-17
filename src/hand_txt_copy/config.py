"""Configuration loading and validation.

The whole app reads its tunables from a single ``Config`` dataclass built from a YAML file, so
logic modules never hard-code thresholds. Loading is intentionally strict: unknown or malformed
values raise ``ConfigError`` at startup rather than failing deep in the real-time loop.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

import yaml


class ConfigError(ValueError):
    """Raised when a configuration file is missing keys or has invalid values."""


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    mirror: bool = True


@dataclass
class HandTrackerConfig:
    max_num_hands: int = 1
    model_complexity: int = 1  # kept for back-compat; unused by the Tasks API
    model_path: str = "models/hand_landmarker.task"
    min_detection_confidence: float = 0.6
    min_hand_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5


@dataclass
class GesturesConfig:
    pinch_on_distance: float = 0.05
    pinch_off_distance: float = 0.08
    debounce_frames: int = 3


@dataclass
class CursorConfig:
    margin_x: float = 0.15
    margin_y: float = 0.15
    one_euro_min_cutoff: float = 1.0
    one_euro_beta: float = 0.007
    one_euro_d_cutoff: float = 1.0


@dataclass
class ScreenConfig:
    monitor: int = 1


@dataclass
class OcrConfig:
    enabled: bool = True
    language: str = "eng"
    tesseract_cmd: str | None = None


@dataclass
class PasteConfig:
    mode: str = "clipboard"  # "clipboard" | "type"
    keystroke: str = "ctrl+v"


@dataclass
class ConsoleConfig:
    move_cursor: bool = True  # move the real OS mouse pointer to follow the fingertip


@dataclass
class OverlayConfig:
    enabled: bool = True
    cursor_radius: int = 12
    cursor_color: tuple[int, int, int] = (0, 200, 255)
    selection_color: tuple[int, int, int] = (0, 200, 255)
    toast_ms: int = 1500


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/hand-txt-copy.log"
    max_bytes: int = 1_048_576
    backup_count: int = 3


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    hand_tracker: HandTrackerConfig = field(default_factory=HandTrackerConfig)
    gestures: GesturesConfig = field(default_factory=GesturesConfig)
    cursor: CursorConfig = field(default_factory=CursorConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    paste: PasteConfig = field(default_factory=PasteConfig)
    console: ConsoleConfig = field(default_factory=ConsoleConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> None:
        """Sanity-check cross-field invariants; raise ``ConfigError`` on problems."""
        g = self.gestures
        if not 0 < g.pinch_on_distance < g.pinch_off_distance:
            raise ConfigError(
                "gestures.pinch_on_distance must be > 0 and < gestures.pinch_off_distance "
                f"(got on={g.pinch_on_distance}, off={g.pinch_off_distance})"
            )
        if g.debounce_frames < 1:
            raise ConfigError("gestures.debounce_frames must be >= 1")
        c = self.cursor
        for name in ("margin_x", "margin_y"):
            v = getattr(c, name)
            if not 0 <= v < 0.5:
                raise ConfigError(f"cursor.{name} must be in [0, 0.5) (got {v})")
        if self.paste.mode not in ("clipboard", "type"):
            raise ConfigError(f"paste.mode must be 'clipboard' or 'type' (got {self.paste.mode!r})")


def _build(cls: type, data: Any, path: str) -> Any:
    """Recursively construct a (possibly nested) dataclass from a plain dict.

    Extra keys raise ``ConfigError`` so typos in the YAML surface immediately instead of being
    silently ignored.
    """
    if not is_dataclass(cls):
        return data
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path or 'root'}: expected a mapping, got {type(data).__name__}")

    # Resolve string annotations (from ``from __future__ import annotations``) to real types.
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{path or 'root'}: unknown keys {sorted(unknown)}")

    kwargs: dict[str, Any] = {}
    for name in known:
        if name not in data:
            continue  # fall back to the dataclass default
        child_path = f"{path}.{name}" if path else name
        f_type = hints.get(name)
        if is_dataclass(f_type):
            kwargs[name] = _build(f_type, data[name], child_path)
        else:
            value = data[name]
            # Normalise RGB lists to tuples for the color fields.
            if isinstance(value, list) and name.endswith("color"):
                value = tuple(value)
            kwargs[name] = value
    return cls(**kwargs)


def load_config(path: str | Path) -> Config:
    """Load, build, and validate a :class:`Config` from a YAML file."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough of parser message
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    cfg: Config = _build(Config, raw, "")
    cfg.validate()
    return cfg


def _tuples_to_lists(value: Any) -> Any:
    """Recursively convert tuples to lists so ``yaml.safe_dump`` can serialize them."""
    if isinstance(value, tuple):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, list):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, dict):
        return {k: _tuples_to_lists(v) for k, v in value.items()}
    return value


def save_config(cfg: Config, path: str | Path) -> None:
    """Validate and write ``cfg`` to ``path`` as YAML.

    The output is a complete, valid config (without the inline comments of the hand-authored
    template) — the calibration tool writes a per-station file this way, leaving ``default.yaml``
    intact as the documented reference.
    """
    cfg.validate()
    data = _tuples_to_lists(asdict(cfg))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by `hand-txt-copy --calibrate`. Edit config/default.yaml for the\n")
        fh.write("# documented template with comments.\n")
        yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
