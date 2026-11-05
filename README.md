# SHRADDHA AI 🎙️

A lightweight, **local-first**, **Hindi-first** voice assistant for Windows 10.

No cloud. No API keys. No subscription. No telemetry. It works with the network cable unplugged.

> **Status:** Phase 0 — repository skeleton, configuration, storage, diagnostics and CI.
> There is no microphone, speech or UI code yet. See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Why this exists

Commercial voice assistants are cloud products: your voice leaves the machine, the
assistant stops working offline, and it stops working entirely when a vendor changes
its pricing. SHRADDHA AI is the opposite: it listens, understands, answers and speaks
**entirely on your own PC**, in Hindi and Hinglish, on hardware you already own.

Design priorities, in order:

1. **Low resource usage** — must stay usable on a 4 GB Windows 10 laptop.
2. **Fast** — sub-400 ms hotkey-to-listening; no browser engine, no background daemon.
3. **Hindi voice** — Devanagari + Hinglish input, natural Hindi output.
4. **Zero paid APIs** — every component is free and runs locally.

## Quick start (development)

```bash
git clone https://github.com/dewdaboss/shraddha-AI-.git
cd shraddha-AI-
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate
pip install -e ".[dev]"

python -m shraddha --version
python -m shraddha --doctor     # environment + capability report
python -m shraddha --init       # create config, database and folders
```

The core package has **zero third-party dependencies**. Heavy components
(Qt, ONNX Runtime, ASR/TTS models, the LLM) are optional extras loaded lazily,
so an unused feature costs no RAM.

Optional extras:

```bash
pip install -e ".[ui]"          # PySide6 UI
pip install -e ".[audio]"       # microphone capture
pip install -e ".[asr]"         # sherpa-onnx speech recognition
pip install -e ".[tts-piper]"   # neural Hindi TTS
pip install -e ".[win]"         # Windows SAPI/OneCore voices
```

## Hindi voice support

| Layer | Engine | Notes |
|---|---|---|
| Recognition | **sherpa-onnx** + Hindi IndicConformer (int8) | offline, streaming, ~130 MB |
| Recognition (light) | **Vosk** `small-hi` | ~42 MB, fallback for weak CPUs |
| Speech, tier 1 | **Windows built-in** — Hemant (m) / Kalpana (f) | zero download, zero RAM, ships with Windows |
| Speech, tier 2 | **Piper** `hi_IN` neural voices | ~63 MB, more natural — see licence caveat below |

⚠️ **Licence caveat:** the Piper Hindi voices (`pratham`, `priyamvada`, `rohan`) were
trained on non-commercial / research-only audio. They are fine for personal use but
**not for a paid product**. Windows' own voices are licensed with the OS and are the
commercially safe default. Full details in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Resource budget

| State | Target resident memory | Target CPU |
|---|---|---|
| Tray, idle, nothing loaded | ≤ 90 MB | ~0 % |
| Listening (VAD + ASR) | ≤ 350 MB | 5–15 % of one core while speaking |
| Speaking (Piper) | ≤ 450 MB | burst, < 1 s per sentence |
| Optional LLM (Phase 6) | +2.5–3.5 GB, transient | killed after 60 s idle |

These are budgets, not claims. CI measures them; regressions fail the build.

## Repository layout

```
src/shraddha/        core package (stdlib only)
  config.py          typed configuration, JSON persistence
  paths.py           %LOCALAPPDATA% layout, overridable for tests
  logging_setup.py   rotating file logs, never crashes the app
  doctor.py          environment & capability diagnostics
  storage/db.py      SQLite schema + migrations
  speech/            TTS engine abstraction (more in later phases)
docs/                architecture, roadmap, model provisioning
scripts/             model download helper (models are never committed)
tests/               pytest suite, runs on Linux CI too
```

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design rules that keep this
app small. The short version: **rules before models, lazy before eager, and measure
everything.**

## Licence

Code: [MIT](LICENSE). Model weights and voices: their own terms — see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
