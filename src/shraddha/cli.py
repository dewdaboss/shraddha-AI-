"""Command-line entry point.

Phase 0 exposes only diagnostics and setup. The assistant itself (tray + microphone)
arrives in Phase 1 and will be launched with ``shraddha run``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from shraddha import APP_NAME, __version__
from shraddha.config import AppConfig, ConfigError
from shraddha.doctor import run_doctor
from shraddha.logging_setup import get_logger, setup_logging
from shraddha.paths import Paths, get_paths

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_IMPLEMENTED = 3
EXIT_NO_QT = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shraddha",
        description=f"{APP_NAME} AI - a local-first Hindi voice assistant for Windows 10.",
        epilog="Nothing leaves your computer: no cloud, no API keys, no telemetry.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} AI {__version__}")
    parser.add_argument("--doctor", action="store_true", help="report environment and capabilities")
    parser.add_argument(
        "--json", action="store_true", help="machine-readable output (with --doctor)"
    )
    parser.add_argument("--init", action="store_true", help="create folders, config and database")
    parser.add_argument(
        "--ui",
        action="store_true",
        help="start the desktop assistant (tray + overlay); requires the 'ui' extra",
    )
    parser.add_argument(
        "--smoke",
        type=float,
        default=None,
        metavar="SECONDS",
        help=argparse.SUPPRESS,  # internal: start the UI, report READY, exit after N s
    )
    parser.add_argument("--verbose", action="store_true", help="debug-level logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.doctor or args.init or args.ui or args.smoke is not None):
        parser.print_help()
        return EXIT_OK

    paths = get_paths()
    if args.ui or args.smoke is not None:
        # Imported here, not at module level: Qt costs ~90 ms and the CLI must stay fast.
        from shraddha.ui.app import run_ui

        return run_ui(paths=paths, smoke_seconds=args.smoke)

    setup_logging(level="DEBUG" if args.verbose else "INFO", log_file=paths.log_file, console=False)

    if args.init:
        return _run_init(paths)
    return _run_doctor(paths, as_json=args.json)


def _run_init(paths: Paths) -> int:
    log = get_logger("cli")
    try:
        paths.ensure()
        if paths.config_file.exists():
            config = AppConfig.load(paths.config_file)
            print(f"config already exists, kept as is: {paths.config_file}")
        else:
            config = AppConfig()
            config.save(paths.config_file)
            print(f"config created: {paths.config_file}")

        from shraddha.storage import db as db_module

        version = db_module.initialize(paths.db_file)
        print(f"database ready: {paths.db_file} (schema v{version})")
        print(f"models folder:  {paths.models}")
        print(f"logs folder:    {paths.logs}")
        print()
        print("next steps:")
        print("  1. python -m shraddha --doctor      # check what this machine supports")
        print("  2. python scripts/fetch_models.py --set all-light")
        print("  3. pip install -e '.[ui,audio,asr,win]'   # Phase 1+ components")
        return EXIT_OK
    except (OSError, ConfigError) as exc:
        log.error("initialisation failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _run_doctor(paths: Paths, as_json: bool) -> int:
    report = run_doctor(paths)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.to_text())
    if not report.config_ok:
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through -m
    sys.exit(main())
