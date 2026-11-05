# SHRADDHA AI — Architecture

> Target: Windows 10 22H2 x64 (Windows 11 compatible). Python 3.11–3.13.
> Goal: a Hindi voice assistant that is useful on a 4 GB laptop with no internet.

## 1. Process model

```
┌────────────────────────────── shraddha.exe (Python, Qt optional) ──────────────────────────────┐
│  TRAY + OVERLAY  (hidden most of the time; no browser engine, no daemon)                       │
│        ↑ hotkey Ctrl+Alt+S            ↑ wake word (opt-in)           ↑ tray menu               │
│  ┌─────┴────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ PIPELINE (in-process, event driven)                                                     │  │
│  │  mic 16 kHz mono ──▶ ring buffer ──▶ VAD gate ──▶ ASR ──▶ text                           │  │
│  └───────────────────────────────────────────────┬─────────────────────────────────────────┘  │
│                                                  ▼                                             │
│  ┌──────────────┐   ┌────────────────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│  │ INTENT ROUTER│──▶│ SKILLS             │──▶│ REPLY COMPOSER   │──▶│ TTS (OneCore|Piper)  │  │
│  │ rules first  │   │ open app, timer,   │   │ template, no LLM │   │                      │  │
│  │ ~0 CPU       │   │ notes, clipboard   │   │                  │   │                      │  │
│  └──────────────┘   └────────────────────┘   └──────────────────┘   └──────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ SQLite: history, settings, notes, metrics        config.json                           │  │
│  └────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────┬───────────────────────────────────────────────────────────────────────┘
                        │ spawn on demand · kill after 60 s idle · named pipe / JSON lines
            ┌───────────▼────────────┐                  ┌──────────────────────────────┐
            │ asr_worker (process)   │                  │ llm_worker (Phase 6 only)    │
            │ sherpa-onnx + int8     │                  │ llama.cpp + Qwen3-4B Q4_K_M  │
            │ reclaimable RAM        │                  │ 2.5–3.5 GB while loaded      │
            └────────────────────────┘                  └──────────────────────────────┘
```

**Implemented in Phase 1:** tray, overlay, hotkey, single instance, text chat, SQLite
history. **Still stubbed:** the microphone (VAD + ASR), speech output and the LLM.

**Three rules drive every decision:**

1. **Rules before models.** Deterministic commands ("Chrome kholo", "10 minute ka timer")
   are matched by a hand-written grammar. No neural network is touched. This is the
   single largest CPU saving and it makes common commands instant and 100 % reliable.
2. **Lazy before eager.** Nothing heavy is imported or loaded at startup. `import
   onnxruntime`, `import sherpa_onnx` and model sessions happen on first use; they are
   released when idle. Startup must not pay for features you are not using.
3. **Separate what must die.** Models that cost hundreds of megabytes (ASR, LLM) live
   in child processes so "unload" is `terminate()`, not a hope that the garbage
   collector does the right thing.

## 2. Why Python, and what it costs

Python was chosen deliberately for AI-library access and development speed. The honest
price:

| Aspect | .NET/WPF | **Python + Qt (chosen)** |
|---|---|---|
| Idle RAM | 35–55 MB | **60–90 MB** |
| Active RAM (ASR+TTS) | 350 MB | **400–500 MB** |
| Cold start | 400 ms | **1.2–2 s** (mitigated by Nuitka + lazy imports) |
| Installer size | 5–70 MB | 45–90 MB (framework-dependent Qt vs bundled) |
| Dev speed for speech AI | good | **best** |

Mitigations that keep Python acceptable:
- **No PyTorch.** ONNX Runtime only; `torch` alone is a ~2 GB install.
- **No `import` at module top-level** for anything in `[ui]`, `[audio]`, `[asr]`, `[tts]` extras.
- **Nuitka standalone one-folder build** (C-compiled, ~40 % faster startup, lower RSS than
  PyInstaller one-file, which re-extracts a zip to `%TEMP%` on every launch).
- `gc.freeze()` after startup and a raised allocation threshold to avoid GC churn.

## 3. Module responsibilities

| Module | Responsibility | Must NOT |
|---|---|---|
| `paths.py` | one place that knows where files live (`%LOCALAPPDATA%\Shraddha`) | guess paths elsewhere |
| `instance.py` | exclusive lock file with stale-PID recovery | assume the OS cleans up after a crash |
| `hotkey.py` | parse "ctrl+alt+s" into Win32 modifiers + virtual key | call ctypes |
| `assistant.py` | deterministic Hindi/Hinglish replies + the Phase 4/6 seam | touch the network |
| `speech/asr.py` | recogniser protocol + honest "not yet" placeholder (Phase 1 seam) | load a model at import |
| `ui/theme.py` | design tokens and stylesheet (Qt-free) | import Qt |
| `ui/overlay.py` | the floating card: chat, input, mic, animation | contain business logic |
| `ui/chat.py` | transcript view, bounded to 200 bubbles | parse markup |
| `ui/tray.py` | tray icon, menu, notifications, degradation | crash when no tray exists |
| `ui/hotkey.py` | `RegisterHotKey` + Qt native event filter | install a keyboard hook |
| `ui/ipc.py` | local socket so a second launch wakes the first | carry any real data |
| `ui/app.py` | wiring: controller, lifecycle, persistence | own layout code |
| `core/config.py` | typed config, defaults, validation, atomic save | import heavy deps |
| `core/logging_setup.py` | rotating logs; degrade silently if disk is unwritable | raise into the UI |
| `core/doctor.py` | capability detection (RAM, voices, models, extras) | mutate state |
| `storage/db.py` | SQLite schema + versioned migrations | hold long-lived connections |
| `speech/tts.py` | engine registry + selection policy | block the caller's UI thread |
| `speech/vad.py` | energy VAD + utterance segmenter (pure Python, no numpy) | know about ASR |
| `speech/audio.py` | PortAudio capture, device list, typed microphone errors | touch Qt |
| `speech/engines/base.py` | `OfflineRecognizer` protocol, `AsrError`, guarded `load()` | choose an engine |
| `speech/engines/vosk_engine.py` | Vosk small-hi: model discovery, decode | run in the GUI thread |
| `speech/engines/sherpa_engine.py` | IndicConformer int8 via sherpa-onnx | run in the GUI thread |
| `speech/engines/__init__.py` | engine registry + `auto` policy + doctor report | import a model at import time |
| `speech/wake.py` | wake-phrase matching (Latin + Devanagari, bounded edit distance) | run ASR |
| `speech/service.py` | pipeline: capture → VAD → ASR → wake gate → events; idle unload | touch Qt or the file system |
| `commands/apps.py` | the allowlists: apps, URLs, Windows known folders | execute anything |
| `commands/router.py` | Hindi/Hinglish sentence → validated intent (pure) | launch a process |
| `commands/actions.py` | **the only module that launches a process or opens a folder** | trust a transcript |
| `commands/confirmation.py` | spoken yes/no gate for sensitive actions | assume silence is consent |
| `ui/voice.py` | Qt bridge: worker thread → signals, no polling timers | decode audio on the GUI thread |
| `ui/app.py` | wiring: controller, lifecycle, persistence, command dispatch | own layout code |

## 4. Threading and CPU discipline

- **One audio callback thread** (PortAudio) whose only job is `queue.put_nowait(frame)`
  into a bounded queue. No allocations, no resize, no numpy. A full queue drops a frame
  rather than stalling the device.
- **One voice worker thread** (`shraddha-voice`) owned by `ui/voice.py`. It blocks on
  that queue with a 100 ms timeout, runs VAD, and runs the ASR. When the queue is empty
  it calls `tick()`, which is where the idle model unload happens — so even that work is
  off the GUI thread.
- **VAD runs before ASR**, always: the recogniser only ever sees a complete utterance,
  which is why a 42 MB model can decode in a few hundred milliseconds and why the
  microphone can stay open in wake mode without burning CPU.
- **No polling.** No `while True: sleep(0.1)`. UI work is driven by Qt signals; timers,
  if unavoidable, are ≥ 1 s and coalesced.
- **Thread caps:** `OMP_NUM_THREADS=2`, ONNX `intra_op_num_threads=2`,
  `enable_cpu_mem_arena=false` so ONNX does not keep arenas forever.
- **Never `RegisterHotKey` + a low-level keyboard hook.** The hook is a known
  AV/EDR false-positive and a measurable CPU cost; `RegisterHotKey` is free.

## 5. Latency budget (hotkey → first sound)

Measured in-budget values are from `scripts/measure_resources.py`; the voice figures are
estimates for a 4-core Windows 10 laptop and are the ones to re-measure on real hardware.

| Stage | Budget |
|---|---|
| Process spawn → window ready | **184 ms measured** (budget 2 s) |
| Hotkey → window shown | 50 ms |
| Mic warm-up + VAD arm | 100 ms |
| End of speech → transcript | 250–600 ms (int8 streaming ASR, ~1 s utterances) |
| Intent match | < 5 ms |
| TTS first audio (OneCore) | < 120 ms |
| TTS first audio (Piper) | 300–700 ms, incl. one-time 6 s model load |

## 6. The voice pipeline (Phase 2)

`speech/` never imports `subprocess`; `commands/` never imports a microphone. That split
is the enforcement mechanism for "never execute recognised speech directly".

| Stage | Module | Thread | Failure behaviour |
|---|---|---|---|
| capture | `speech/audio.py` | PortAudio | `MicrophoneError` → Hindi notice, text chat keeps working |
| detect speech | `speech/vad.py` | worker | never fails: pure arithmetic |
| segment | `speech/vad.py` | worker | clicks < 250 ms dropped; 15 s hard cap |
| recognise | `speech/engines/` | worker | `AsrError` → user message + hint; pipeline survives |
| wake gate | `speech/wake.py` | worker | unmatched speech → `ignored` event, not a command |
| route | `commands/router.py` | GUI (pure, <1 ms) | unknown → chat layer answers |
| confirm | `commands/confirmation.py` | GUI | unclear → question stays open |
| act | `commands/actions.py` | GUI | not allowlisted → refusal, nothing runs |

Memory policy, in one sentence: **a model exists only between "user starts speaking" and
`asr.idle_unload_s` after the last utterance**, and the same rule applies to wake mode with
its own (shorter) timer.

## 7. Failure and privacy rules

- **Offline is normal, not an error state.** No feature may require the network except
  the one-time model download.
- **No audio leaves the machine.** No crash reporter, no analytics, no auto-update
  pings. Model downloads are the only outbound request and are explicit, user-initiated
  and checksum-verified.
- **Degrade, don't crash:** if the mic is missing, run text-only. If a model is missing,
  fall back to the lighter engine. If TTS fails, show the text.
- **Single instance** via a named mutex / lock file — a second launch focuses the first.

## 8. Packaging

| Concern | Choice |
|---|---|
| Build | Nuitka `--standalone --enable-plugin=pyside6` (fallback: PyInstaller one-folder) |
| Installer | Inno Setup 6, per-user `%LOCALAPPDATA%\Programs\Shraddha`, **no admin, no UAC** |
| Models | downloaded on first run with SHA-256 pinning, or bundled in an optional offline installer |
| Signing | optional self-signed cert for internal use; SmartScreen warning otherwise |
| CI | GitHub Actions `windows-latest` for build/smoke, `ubuntu-latest` for fast unit tests |
