# SHRADDHA AI 🎙️

A lightweight, **local-first**, **Hindi-first** voice assistant for Windows 10.

No cloud. No API keys. No subscription. No telemetry. It works with the network cable unplugged.

> **Status: Phase 1 — desktop interface.** A tray icon, a floating overlay, a global
> hotkey, single-instance handling and a working Hindi text chat. Speech recognition
> (Phase 2), speech output (Phase 3) and the optional local AI (Phase 6) are not built yet,
> and the interface says so instead of pretending. See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Why this exists

Commercial voice assistants are cloud products: your voice leaves the machine, the
assistant stops working offline, and it stops working entirely when a vendor changes
its pricing. SHRADDHA AI is the opposite: it listens, understands, answers and speaks
**entirely on your own PC**, in Hindi and Hinglish, on hardware you already own.

Design priorities, in order:

1. **Low resource usage** — must stay usable on a 4 GB Windows 10 laptop.
2. **Fast** — 176 ms from launch to a usable window; no browser engine, no background daemon.
3. **Hindi voice** — Devanagari + Hinglish input, natural Hindi output.
4. **Zero paid APIs** — every component is free and runs locally.

## What works today

| Feature | Status |
|---|---|
| System tray icon with menu (open / clear chat / quit) | ✅ Phase 1 |
| Floating overlay: black + neon, rounded, always-on-top, draggable | ✅ Phase 1 |
| Global hotkey `Ctrl+Alt+S` (Win32 `RegisterHotKey`, no keyboard hook) | ✅ Phase 1 |
| Single instance + "wake the running window" IPC | ✅ Phase 1 |
| Text command input and Hindi chat transcript | ✅ Phase 1 |
| Conversation history in SQLite, restored on restart | ✅ Phase 1 |
| Microphone button (UI + state machine) | ✅ Phase 1 (wired to a placeholder) |
| Hindi speech recognition | ⏳ Phase 2 |
| Hindi speech output | ⏳ Phase 3 |
| Intent grammar and system skills | ⏳ Phase 4 |
| Optional local LLM | ⏳ Phase 6 |

## Quick start

```bash
git clone https://github.com/dewdaboss/shraddha-AI-.git
cd shraddha-AI-
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate

pip install -e ".[dev,ui]"     # dev tools + PySide6
python -m shraddha --init       # config, database, folders
python -m shraddha --ui         # start the assistant
```

Then press **Ctrl+Alt+S** (or click the tray icon) and type, for example:

| You type | You get |
|---|---|
| `नमस्ते` | a greeting |
| `समय क्या है?` / `kitne baje hain` | the current time |
| `आज कौन सी तारीख़ है?` | today's date in Hindi |
| `मदद` | what the assistant can do today |
| anything else | an honest "no language model connected yet" |

The core package has **zero third-party dependencies**. Qt, audio, ASR and TTS are optional
extras loaded lazily, so an unused feature costs no memory.

```bash
pip install -e ".[ui]"          # PySide6 desktop interface
pip install -e ".[audio]"       # microphone capture (Phase 2)
pip install -e ".[asr]"         # sherpa-onnx speech recognition (Phase 2)
pip install -e ".[tts-piper]"   # neural Hindi TTS (Phase 3)
pip install -e ".[win]"         # Windows SAPI/OneCore voices (Phase 3)
```

## Measured performance

From `python scripts/measure_resources.py` on the development sandbox
(Linux, Qt `minimal` platform, no fonts, no GPU — run it on Windows for the real numbers):

| Metric | Value | Budget |
|---|---|---|
| import core (`doctor`, `config`, `storage`) | 43 ms | — |
| import Qt UI | 43 ms | — |
| spawn → UI ready | **176 ms** | ≤ 2 s ✅ |
| resident memory, idle | **61.8 MB** | ≤ 90 MB ✅ |
| background processes | **0** | 0 ✅ |
| heavy AI libraries imported at startup | **none** | none ✅ |

A CI job fails the build if `onnxruntime`, `numpy`, `torch`, `sherpa_onnx` or Qt is ever
imported on the CLI path.

## Hindi voice stack (planned, all free and local)

| Layer | Engine | Notes |
|---|---|---|
| Recognition | **sherpa-onnx** + Hindi IndicConformer (int8) | offline, streaming, ~130 MB |
| Recognition (light) | **Vosk** `small-hi` | ~42 MB, fallback for weak CPUs |
| Speech, tier 1 | **Windows built-in** — Hemant (m) / Kalpana (f) | zero download, zero RAM |
| Speech, tier 2 | **Piper** `hi_IN` neural voices | ~63 MB, more natural — see licence caveat |

⚠️ **Licence caveat:** the Piper Hindi voices (`pratham`, `priyamvada`, `rohan`) were
trained on non-commercial / research-only audio. They are fine for personal use but
**not for a paid product**. Windows' own voices are licensed with the OS and are the
commercially safe default. Full details in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Commands

```bash
python -m shraddha --version
python -m shraddha --doctor          # environment + capability report (--json for machines)
python -m shraddha --init            # create config, database and folders
python -m shraddha --ui              # start the desktop assistant
python scripts/fetch_models.py --list
python scripts/measure_resources.py  # startup time and resident memory
pytest                               # 197 tests
```

## Repository layout

```
src/shraddha/
  config.py          typed configuration, atomic JSON persistence
  paths.py           %LOCALAPPDATA% layout, overridable for tests
  logging_setup.py   rotating file logs, never crashes the app
  doctor.py          environment & capability diagnostics
  instance.py        single-instance lock with stale-PID recovery
  hotkey.py          hotkey parsing -> Win32 modifier/virtual-key codes
  assistant.py       deterministic Hindi replies (the Phase 4/6 seam)
  speech/            TTS engine detection, ASR protocol placeholder
  storage/db.py      SQLite schema + migrations
  ui/                theme, overlay, chat, tray, hotkey, ipc, app wiring
docs/                architecture, UI design notes, roadmap, model provisioning
scripts/             model downloader, resource measurement
tests/               pytest suite (runs headless on Linux, including the Qt tests)
```

## Testing notes

The Qt tests run headless via the `minimal` platform plugin, so widget construction,
layout, signals, chat behaviour and painting are all covered on Linux and in CI. Three
things need a real Windows 10 machine and are listed in [docs/UI.md](docs/UI.md#what-could-not-be-verified-on-linux):
global hotkey delivery, the tray icon, and Devanagari font shaping.

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design rules that keep this
app small. The short version: **rules before models, lazy before eager, and measure
everything.**

## Licence

Code: [MIT](LICENSE). Model weights and voices: their own terms — see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
