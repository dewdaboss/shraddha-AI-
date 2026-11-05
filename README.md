# SHRADDHA AI 🎙️

A lightweight, **local-first**, **Hindi-first** voice assistant for Windows 10.

No cloud by default. No API keys required. No subscription. No telemetry. It works with
the network cable unplugged.

> **Status: Phase 3 — optional cloud answers.** Press the microphone (or say "श्रद्धा, …")
> and speak Hindi or Hinglish; the words are recognised **on your machine**, routed through
> an allowlist, executed, and answered out loud in Hindi. Questions the rule engine cannot
> answer can now be sent to **Google Gemini — but only after you add a key *and* grant
> consent inside the app**. Until then nothing leaves the computer. See
> [docs/AI.md](docs/AI.md).
>
> **What has not been verified here:** the real microphone/PortAudio path, the Windows
> voices, recognition accuracy on live speech, and everything that needs a real Gemini key
> (Credential Manager storage, a live round-trip, free-tier quota). The development sandbox
> has no audio hardware and no API key; those parts are marked *hardware-dependent* in
> [docs/VOICE.md](docs/VOICE.md#12-verification-what-is-tested-and-what-is-not) and
> [docs/AI.md](docs/AI.md#11-what-is-verified-and-what-is-not).

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
4. **Zero paid services** — every default component is free and runs locally; the one
   optional cloud feature (Gemini) uses a free tier and is off until you turn it on.

## What works today

| Feature | Status |
|---|---|
| System tray icon with menu (open / clear chat / quit) | ✅ Phase 1 |
| Floating overlay: black + neon, rounded, always-on-top, draggable | ✅ Phase 1 |
| Global hotkey `Ctrl+Alt+S` (Win32 `RegisterHotKey`, no keyboard hook) | ✅ Phase 1 |
| Single instance + "wake the running window" IPC | ✅ Phase 1 |
| Text command input and Hindi chat transcript | ✅ Phase 1 |
| Conversation history in SQLite, restored on restart | ✅ Phase 1 |
| Microphone button, mute/unmute, live listening status | ✅ Phase 2 (logic tested; needs a real mic) |
| Offline Hindi/Hinglish speech recognition (Vosk 42 MB, sherpa-onnx optional) | ✅ Phase 2 (engine logic tested; accuracy needs your machine) |
| Wake word "श्रद्धा" / "Hey Shraddha", push-to-talk, or off | ✅ Phase 2 (matcher tested) |
| Hindi command layer: open apps/folders/sites, date, time, stop listening, change voice | ✅ Phase 2 (40+ sentence corpus tested) |
| Safety: allowlists, no shell, spoken confirmation, power actions refused | ✅ Phase 2 |
| Hindi spoken replies (Windows OneCore + optional Piper) | ✅ Phase 2 (Windows synthesis is hardware-dependent) |
| Idle model unloading, no always-on heavy model | ✅ Phase 2 |
| Cloud answers (Google Gemini), **opt-in**, streamed into the chat | ✅ Phase 3 (mocked in tests; needs a real key on Windows) |
| Provider layer with a model fallback (`gemini-flash-latest` → `gemini-2.5-flash`) | ✅ Phase 3 |
| Keys from env vars or the Windows Credential Manager, never in `config.json` | ✅ Phase 3 (logic tested with a fake store) |
| Offline / rate-limit / invalid-key / retired-model handling, in Hindi | ✅ Phase 3 |
| The model can never open apps or run commands (test-enforced) | ✅ Phase 3 |
| System skills beyond the allowlist (volume, files, windows) | ⏳ Phase 4 |
| Optional local LLM (llama.cpp, no network at all) | ⏳ Phase 6 |

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
pip install -e ".[audio]"       # microphone capture (PortAudio)
pip install -e ".[asr-vosk]"    # Vosk: 42 MB Hindi model, best for 4 GB machines
pip install -e ".[asr]"         # sherpa-onnx + IndicConformer: better accuracy, more RAM
pip install -e ".[tts-piper]"   # neural Hindi voice (non-commercial licence)
pip install -e ".[win]"         # Windows SAPI/OneCore voices
```

### Voice quick start

```bash
pip install -e ".[ui,audio,asr-vosk,win]"
python scripts/fetch_models.py --set asr-light   # 42 MB, Apache-2.0, unzipped automatically
python -m shraddha --doctor                      # microphone + engine + voice report
python -m shraddha --ui
```

Then press **Ctrl+Alt+S**, click the microphone, and say *"श्रद्धा, Chrome खोलो।"*
Full details, tuning and troubleshooting: [docs/VOICE.md](docs/VOICE.md).

### Optional: cloud answers (off by default)

```bash
pip install -e ".[ai]"                   # official google-genai SDK
python -m shraddha --set-api-key         # hidden prompt -> Windows Credential Manager
python -m shraddha --ai-check            # one real round-trip, prints the answer
python -m shraddha --ai-consent          # or type "क्लाउड AI चालू करो" in the chat
```

`python -m shraddha --ai-status` shows the provider, the model, where the key came from
(masked) and whether consent is granted; `--ai-off` switches it back off. Nothing is sent
to Google until the key **and** the consent are both present, and PC actions always stay
local. Details: [docs/AI.md](docs/AI.md).

## Measured performance

From `python scripts/measure_resources.py` on the development sandbox
(Linux, Qt `minimal` platform, no fonts, no GPU — run it on Windows for the real numbers):

| Metric | Value | Budget |
|---|---|---|
| import core (`doctor`, `config`, `storage`) | 48 ms | — |
| import Qt UI | 56 ms | — |
| spawn → UI ready | **200 ms** | ≤ 2 s ✅ |
| resident memory, idle (voice + AI layers, no SDK loaded) | **64.4 MB** | ≤ 90 MB ✅ |
| background processes | **0** | 0 ✅ |
| heavy AI libraries imported at startup | **none** (`google-genai` is imported lazily, on the worker, after consent) | none ✅ |

A CI job fails the build if `onnxruntime`, `numpy`, `torch`, `sherpa_onnx`, `vosk` or Qt
is ever imported on the CLI path — which is why startup stays instant and idle RAM stays
at two figures. With the small Hindi model **loaded** the expected footprint is
180–300 MB, and the model is dropped again after 120 s of silence.

## Hindi voice stack (all free, all local)

| Layer | Engine | Licence | Notes |
|---|---|---|---|
| Recognition (default) | **Vosk** `vosk-model-small-hi-0.22` | Apache-2.0 ✅ | 42 MB, ~100–200 MB RSS, no ONNX Runtime |
| Recognition (optional) | **sherpa-onnx** + Hindi IndicConformer int8 | CC-BY-4.0 ✅ | ~130 MB model, better on accents/noise, +60–90 MB runtime |
| Speech, tier 1 | **Windows built-in** — Hemant (m) / Kalpana (f) | with Windows ✅ | zero download, zero extra RAM |
| Speech, tier 2 | **Piper** `hi_IN` neural voices | CC-BY-NC-SA ❌ | ~63 MB, most natural, **non-commercial only** |
| Wake word | VAD + short-burst ASR + fuzzy matcher | — | no dedicated wake model, nothing always-on |

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
python -m shraddha --ai-status       # cloud AI: provider, model, key source, consent
python -m shraddha --ai-consent      # opt in to Google Gemini  (--ai-off to opt out)
python -m shraddha --set-api-key     # store a Gemini key in the Credential Manager
python -m shraddha --ai-check        # one real round-trip; prints the answer
python scripts/fetch_models.py --list
python scripts/measure_resources.py  # startup time and resident memory
pytest                               # 615 tests
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
  speech/vad.py      pure-Python energy VAD + utterance segmenter (no numpy)
  speech/audio.py    PortAudio capture, device listing, clear mic errors
  speech/engines/    Vosk and sherpa-onnx recognisers + engine selection policy
  speech/wake.py     wake-phrase matching (Latin + Devanagari, bounded edit distance)
  speech/service.py  the pipeline: capture -> VAD -> ASR -> wake gate -> events
  speech/tts.py      engine detection *and* synthesis (OneCore, Piper, null)
  commands/apps.py   the allowlists: apps, URLs, Windows known folders
  commands/router.py Hindi/Hinglish sentences -> intents (pure, no I/O)
  commands/actions.py the only module that launches a process or opens a folder
  commands/confirmation.py spoken yes/no gate for sensitive actions
  ai/                OPTIONAL cloud intelligence: gate, key handling, Gemini provider
  ai/service.py      the three-way gate + history + retry + Hindi error translation
  ai/gemini.py       google-genai provider (lazy import, one-level model fallback)
  ai/keys.py         env vars -> Windows Credential Manager, masked everywhere
  storage/db.py      SQLite schema + migrations
  ui/                theme, overlay, chat, tray, hotkey, ipc, voice bridge, AI bridge,
                     app wiring
docs/                architecture, voice pipeline, UI notes, roadmap, model provisioning
scripts/             model downloader, resource measurement
tests/               pytest suite (runs headless on Linux, including the Qt tests)
```

## Testing notes

615 tests, no network, no API keys, no audio hardware: the voice pipeline is driven with
synthetic frames and fake recognisers, the Gemini SDK is replaced by a fake client, and the
Qt tests run headless via the `minimal` platform plugin. Nothing is launched, nothing is
downloaded and nothing is sent anywhere during a test run.

What still needs a real Windows 10 machine: microphone capture, recognition accuracy on
live speech, Windows voice synthesis, global hotkey delivery, the tray icon, Devanagari
font shaping, Credential Manager key storage, and a live Gemini round-trip. See [docs/VOICE.md](docs/VOICE.md#12-verification-what-is-tested-and-what-is-not)
and [docs/UI.md](docs/UI.md#what-could-not-be-verified-on-linux).

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design rules that keep this
app small. The short version: **rules before models, lazy before eager, and measure
everything.**

## Licence

Code: [MIT](LICENSE). Model weights and voices: their own terms — see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
