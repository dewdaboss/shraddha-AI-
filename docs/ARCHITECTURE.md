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
| `speech/asr.py` | recogniser protocol + honest "not yet" placeholder | load a model at import |
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
| `speech/asr.py` | (Phase 2) streaming recognition over a child process | load a model at import |
| `intent/router.py` | (Phase 4) Hindi/Hinglish grammar → intent | call an LLM for known intents |
| `ui/` | (Phase 1) tray, overlay, settings | contain business logic |

## 4. Threading and CPU discipline

- **One audio callback thread** (PortAudio) writing into a pre-allocated ring buffer.
  No allocations per frame, no `numpy.append`.
- **One ASR thread** blocked on a queue when nobody speaks. VAD runs before ASR, so the
  recogniser only sees frames that contain speech.
- **No polling.** No `while True: sleep(0.1)`. UI work is driven by Qt signals; timers,
  if unavoidable, are ≥ 1 s and coalesced.
- **Thread caps:** `OMP_NUM_THREADS=2`, ONNX `intra_op_num_threads=2`,
  `enable_cpu_mem_arena=false` so ONNX does not keep arenas forever.
- **Never `RegisterHotKey` + a low-level keyboard hook.** The hook is a known
  AV/EDR false-positive and a measurable CPU cost; `RegisterHotKey` is free.

## 5. Latency budget (hotkey → first sound)

| Stage | Budget |
|---|---|
| Hotkey → window shown | 50 ms |
| Mic warm-up + VAD arm | 100 ms |
| End of speech → transcript | 250–600 ms (int8 streaming ASR, ~1 s utterances) |
| Intent match | < 5 ms |
| TTS first audio (OneCore) | < 120 ms |
| TTS first audio (Piper) | 300–700 ms, incl. one-time 6 s model load |

## 6. Failure and privacy rules

- **Offline is normal, not an error state.** No feature may require the network except
  the one-time model download.
- **No audio leaves the machine.** No crash reporter, no analytics, no auto-update
  pings. Model downloads are the only outbound request and are explicit, user-initiated
  and checksum-verified.
- **Degrade, don't crash:** if the mic is missing, run text-only. If a model is missing,
  fall back to the lighter engine. If TTS fails, show the text.
- **Single instance** via a named mutex / lock file — a second launch focuses the first.

## 7. Packaging

| Concern | Choice |
|---|---|
| Build | Nuitka `--standalone --enable-plugin=pyside6` (fallback: PyInstaller one-folder) |
| Installer | Inno Setup 6, per-user `%LOCALAPPDATA%\Programs\Shraddha`, **no admin, no UAC** |
| Models | downloaded on first run with SHA-256 pinning, or bundled in an optional offline installer |
| Signing | optional self-signed cert for internal use; SmartScreen warning otherwise |
| CI | GitHub Actions `windows-latest` for build/smoke, `ubuntu-latest` for fast unit tests |
