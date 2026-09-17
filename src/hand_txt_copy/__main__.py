"""Entry point: parse args, load config, wire components, run the real-time loop.

With the overlay enabled the loop is driven by a Qt timer (so the transparent overlay repaints and
stays non-activating). With the overlay disabled it runs a plain loop, which is handy for headless
smoke-testing on a machine without a spare display.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .app import App
from .config import ConfigError, load_config
from .logging_setup import setup_logging

log = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hand-txt-copy", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="path to the YAML config (default: config/default.yaml)",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="launch the live calibration UI instead of running the app",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_CONFIG.with_name("station.yaml"),
        help="where --calibrate saves the tuned config (default: config/station.yaml)",
    )
    return parser.parse_args(argv)


def _run_with_overlay(app: App, target_fps: int) -> int:
    from PySide6 import QtCore, QtWidgets

    from .overlay import Overlay

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    overlay = Overlay(app.cfg.overlay)
    app.overlay = overlay
    overlay.show()
    overlay.notify("hand-txt-copy", "Running — point to move, pinch to select, open palm to paste.")

    app.start()
    timer = QtCore.QTimer()
    timer.timeout.connect(app.tick)
    timer.start(max(1, int(1000 / target_fps)))
    try:
        return qapp.exec()
    finally:
        timer.stop()
        app.stop()


def _run_headless(app: App, target_fps: int) -> int:
    period = 1.0 / target_fps
    app.start()
    log.info("running headless (overlay disabled); press Ctrl+C to stop")
    try:
        while True:
            start = time.perf_counter()
            app.tick()
            elapsed = time.perf_counter() - start
            time.sleep(max(0.0, period - elapsed))
    except KeyboardInterrupt:
        log.info("interrupted")
        return 0
    finally:
        app.stop()


def _bootstrap_error(message: str) -> None:
    """Record a fatal startup error before logging is configured.

    Under ``pythonw`` (silent background launch) there is no console, so stderr is discarded; this
    leaves a trace an admin can read when a double-clicked launcher appears to do nothing.
    """
    print(message, file=sys.stderr)
    try:
        path = Path("logs") / "startup-error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        _bootstrap_error(f"config error: {exc}")
        return 2

    setup_logging(cfg.logging)
    log.info("loaded config from %s", args.config)

    try:
        if args.calibrate:
            from .calibration import run_calibration

            return run_calibration(cfg, str(args.out))

        app = App(cfg)
        if cfg.overlay.enabled:
            return _run_with_overlay(app, cfg.camera.fps)
        return _run_headless(app, cfg.camera.fps)
    except Exception:
        log.exception("fatal error; shutting down")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
