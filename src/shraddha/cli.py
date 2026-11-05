"""Command-line entry point.

Diagnostics, setup and the cloud-AI switches. The assistant itself (tray + overlay)
starts with ``python -m shraddha --ui``.

Cloud AI is opt-in, so every part of it has an explicit command: ``--set-api-key``
stores the key, ``--ai-consent`` opts in, ``--ai-off`` opts out again, ``--ai-status``
shows what would happen, and ``--ai-check`` does one real round-trip so a broken key is
found before the user hits it in the chat window.
"""

from __future__ import annotations

import argparse
import getpass
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

#: Default prompt for ``--ai-check``: short, cheap, and proves Hindi output works.
AI_CHECK_PROMPT = "एक छोटी पंक्ति में बताइए कि आप कौन हैं।"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shraddha",
        description=f"{APP_NAME} AI - a local-first Hindi voice assistant for Windows 10.",
        epilog=(
            "By default nothing leaves your computer: no cloud, no telemetry. "
            "Cloud answers (Google Gemini) are opt-in via --ai-consent."
        ),
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
    parser.add_argument(
        "--set-api-key",
        action="store_true",
        help="store a Gemini API key in the Windows Credential Manager (hidden prompt)",
    )
    parser.add_argument(
        "--ai-check",
        nargs="?",
        const=AI_CHECK_PROMPT,
        default=None,
        metavar="PROMPT",
        help="ask the configured model one question and print the answer (needs a key)",
    )
    parser.add_argument(
        "--ai-consent", action="store_true", help="opt in to sending questions to Google"
    )
    parser.add_argument("--ai-off", action="store_true", help="turn cloud answers off again")
    parser.add_argument(
        "--ai-status", action="store_true", help="show provider, model, key source and consent"
    )
    parser.add_argument("--verbose", action="store_true", help="debug-level logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ai_action = (
        args.set_api_key or args.ai_check is not None or args.ai_consent or args.ai_off or args.ai_status
    )
    if not (args.doctor or args.init or args.ui or args.smoke is not None or ai_action):
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
    if args.set_api_key:
        return _run_set_api_key(paths)
    if args.ai_consent or args.ai_off:
        return _run_consent(paths, grant=bool(args.ai_consent))
    if args.ai_status:
        return _run_ai_status(paths, as_json=args.json)
    if args.ai_check is not None:
        return _run_ai_check(paths, args.ai_check)
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
        print("  3. pip install -e '.[ui,audio,asr,win,ai]'   # desktop + voice + cloud AI")
        print("  4. python -m shraddha --set-api-key  # optional: enable cloud answers")
        return EXIT_OK
    except (OSError, ConfigError) as exc:
        log.error("initialisation failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _load_config(paths: Paths) -> AppConfig:
    """Load the saved config, or the defaults when it does not exist yet."""
    if paths.config_file.exists():
        return AppConfig.load(paths.config_file)
    return AppConfig()


def _save_config(paths: Paths, config: AppConfig) -> None:
    paths.ensure()
    config.save(paths.config_file)


def _run_set_api_key(paths: Paths) -> int:
    from shraddha.ai.keys import CREDENTIAL_TARGET, credential_support, mask_key, write_credential

    supported, reason = credential_support()
    if not supported:
        print(f"the Windows Credential Manager is not available: {reason}", file=sys.stderr)
        print(
            "set the key as an environment variable instead:\n"
            "  setx GEMINI_API_KEY \"your-key\"   (then open a new terminal)",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if not sys.stdin.isatty():  # pragma: no cover - interactive path
        print("--set-api-key needs an interactive terminal", file=sys.stderr)
        return EXIT_ERROR

    try:
        secret = getpass.getpass("Gemini API key (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled", file=sys.stderr)
        return EXIT_ERROR
    if not secret:
        print("no key entered - nothing changed", file=sys.stderr)
        return EXIT_ERROR
    if not secret.startswith("AIza"):
        print("warning: Gemini keys usually start with 'AIza' - storing anyway", file=sys.stderr)

    try:
        write_credential(secret)
    except Exception as exc:
        print(f"could not store the key: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"key stored in the Credential Manager as {CREDENTIAL_TARGET} ({mask_key(secret)})")
    print("check it with: python -m shraddha --ai-check")
    return EXIT_OK


def _run_consent(paths: Paths, grant: bool) -> int:
    config = _load_config(paths)
    if grant:
        config.llm.enabled = True
        config.llm.allow_cloud = True
        if config.llm.provider == "none":
            config.llm.provider = "gemini"
        _save_config(paths, config)
        print("cloud AI: ON - questions the local engine cannot answer are sent to Google.")
        print("turn it off again with: python -m shraddha --ai-off")
    else:
        config.llm.enabled = False
        config.llm.allow_cloud = False
        _save_config(paths, config)
        print("cloud AI: OFF - everything stays on this computer again.")
    return EXIT_OK


def _ai_status_dict(config: AppConfig) -> dict[str, object]:
    from shraddha.ai import key_report, make_service

    keys = key_report(config.llm)
    service = make_service(config.llm)
    try:
        status = service.status()
        message = service.status_message()
    finally:
        service.close()
    return {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "fallback_model": config.llm.fallback_model,
        "enabled": config.llm.enabled,
        "consent": config.llm.allow_cloud,
        "status": status,
        "message": message,
        **keys,
    }


def _run_ai_status(paths: Paths, as_json: bool) -> int:
    config = _load_config(paths)
    info = _ai_status_dict(config)
    if as_json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return EXIT_OK
    key_line = (
        f"present ({info['masked']}, from {info['source']})" if info["present"] else "MISSING"
    )
    print("cloud ai status")
    print("-" * 40)
    print(f"  provider   {info['provider']}")
    print(f"  model      {info['model']} (fallback: {info['fallback_model'] or 'none'})")
    print(f"  enabled    {'yes' if info['enabled'] else 'no'}")
    print(f"  consent    {'yes' if info['consent'] else 'no'}")
    print(f"  api key    {key_line}")
    print(f"  status     {info['status']}")
    if info["message"] and info["status"] != "off":
        for line in str(info["message"]).splitlines():
            print(f"             {line}")
    return EXIT_OK


def _run_ai_check(paths: Paths, prompt: str) -> int:
    from shraddha.ai import AiError, make_service

    config = _load_config(paths)
    service = make_service(config.llm)
    try:
        print(f"asking {config.llm.provider}/{config.llm.model} …")
        answer = service.ask_text(prompt)
    except AiError as exc:
        print(f"failed [{exc.code}]: {exc.user_message()}", file=sys.stderr)
        if exc.code in {"off", "consent_required", "no_key", "no_provider", "no_sdk"}:
            print("hint: python -m shraddha --ai-status", file=sys.stderr)
        return EXIT_ERROR
    finally:
        service.close()
    print(answer)
    model = getattr(service, "_provider", None)
    active = getattr(model, "active_model", None)
    if active and active != config.llm.model:
        print(f"(answered by fallback model {active})")
    return EXIT_OK


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
