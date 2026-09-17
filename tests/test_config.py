from __future__ import annotations

import textwrap

import pytest

from hand_txt_copy.config import Config, ConfigError, load_config, save_config


def _write(tmp_path, text):
    p = tmp_path / "cfg.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_load_defaults_from_empty_sections(tmp_path):
    cfg = load_config(_write(tmp_path, "camera:\n  index: 2\n"))
    assert cfg.camera.index == 2
    assert cfg.gestures.pinch_on_distance == 0.05  # default preserved


def test_unknown_key_raises(tmp_path):
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(_write(tmp_path, "camera:\n  bogus: 1\n"))


def test_pinch_thresholds_must_be_ordered(tmp_path):
    with pytest.raises(ConfigError, match="pinch_on_distance"):
        load_config(_write(tmp_path, "gestures:\n  pinch_on_distance: 0.1\n  pinch_off_distance: 0.05\n"))


def test_color_list_becomes_tuple(tmp_path):
    cfg = load_config(_write(tmp_path, "overlay:\n  cursor_color: [1, 2, 3]\n"))
    assert cfg.overlay.cursor_color == (1, 2, 3)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_save_config_round_trips(tmp_path):
    cfg = Config()
    cfg.camera.index = 3
    cfg.gestures.pinch_on_distance = 0.04
    cfg.overlay.cursor_color = (10, 20, 30)
    out = tmp_path / "station.yaml"
    save_config(cfg, out)

    reloaded = load_config(out)
    assert reloaded.camera.index == 3
    assert reloaded.gestures.pinch_on_distance == 0.04
    assert reloaded.overlay.cursor_color == (10, 20, 30)


def test_save_config_rejects_invalid(tmp_path):
    cfg = Config()
    cfg.gestures.pinch_on_distance = 0.2  # >= off => invalid
    cfg.gestures.pinch_off_distance = 0.1
    with pytest.raises(ConfigError):
        save_config(cfg, tmp_path / "bad.yaml")
