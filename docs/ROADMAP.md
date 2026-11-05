# Roadmap

Each phase ends with something you can run and measure. No phase starts before the
previous one meets its resource budget.

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Skeleton** ✅ | repo layout, config, logging, SQLite, `--doctor`, CI | `python -m shraddha --doctor` reports environment; tests green on Linux + Windows |
| **1 — Desktop interface** ✅ | Qt tray, floating overlay, global hotkey, single instance, chat, mic + text input | idle RSS ≤ 90 MB ✅ (61.8 MB measured, Linux); startup ≤ 2 s ✅ (176 ms); **needs one Windows verification pass** |
| **2 — Hearing (हिन्दी STT)** | PortAudio capture, Silero VAD, sherpa-onnx child process, live transcript in overlay | clean Hindi utterance transcribed < 700 ms; idle CPU ≤ 0.5 % |
| **3 — Speaking (हिन्दी TTS)** | `ITtsEngine` with OneCore + Piper, per-sentence streaming playback, stop/interrupt | first audio < 700 ms; both engines user-switchable |
| **4 — Understanding** | Hindi/Hinglish rule grammar → intents, first skills (open app, timer, note, clipboard, time/date, volume) | ≥ 95 % accuracy on the intent test corpus, < 5 ms/match |
| **5 — Memory** | history in SQLite, "yaad hai?" recall, settings persistence, per-user profile | history survives restart; DB stays < 5 MB after 10k turns |
| **6 — Thinking (optional LLM)** | llama.cpp child process, spawn/idle-kill lifecycle, Hindi prompt template | first token < 3 s on 4 CPU cores; RSS returns to idle after 60 s |
| **7 — Ship** | Nuitka build, Inno Setup installer, first-run model download, signing, release workflow | clean install on a fresh Win10 22H2 VM in < 3 min, works offline |

## Phase 1 carry-over

The interface was built and tested headlessly (Linux, Qt `minimal` platform). These items
can only be confirmed on a real Windows 10 machine:

1. `RegisterHotKey` registration and `WM_HOTKEY` delivery through the native event filter.
2. Tray icon, context menu and balloon notifications.
3. Window opacity fade, always-on-top behaviour and taskbar grouping.
4. Hindi rendering with Nirmala UI, including conjuncts and matras.
5. Real Windows working-set size (expect more than the 62 MB measured on Linux).

## Non-goals

- Cloud sync, accounts, telemetry, crash reporting.
- An app store of third-party skills.
- Beating ChatGPT in Hindi. The LLM is an optional accessory; the assistant must be
  genuinely useful without it.
- Cross-platform support. Windows 10 first; portability only where it is free.

## Open questions to settle before Phase 2

1. **Wake word vs hotkey only.** A hotkey costs 0 % CPU. A custom "Shraddha" wake word
   needs an openWakeWord model trained on synthetic samples (free, but a training run).
   Proposal: ship hotkey in Phase 2, wake word as an opt-in Phase 2.5 experiment.
2. **Hinglish transliteration.** "chrome kholo" arrives as Latin script. Options:
   keep both Roman and Devanagari grammars in the rule engine (free, zero model), or add
   an IndicXlit model (~50 MB). Proposal: grammar first, measure, only then add a model.
3. **Where the overlay lives.** Settled in Phase 1: a 566×486 rounded card, bottom-centre,
   draggable, remembered for the session.
