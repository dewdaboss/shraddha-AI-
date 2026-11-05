# Roadmap

Each phase ends with something you can run and measure. No phase starts before the
previous one meets its resource budget.

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Skeleton** ✅ | repo layout, config, logging, SQLite, `--doctor`, CI | `python -m shraddha --doctor` reports environment; tests green on Linux + Windows |
| **1 — Desktop interface** ✅ | Qt tray, floating overlay, global hotkey, single instance, chat, mic + text input | idle RSS ≤ 90 MB ✅ (61.8 MB measured, Linux); startup ≤ 2 s ✅ (176 ms); **needs one Windows verification pass** |
| **2 — Hearing (हिन्दी STT)** ✅ | PortAudio capture, energy VAD, Vosk small-hi (sherpa-onnx opt-in), wake word, mute, Hindi/Hinglish command layer, safety gates, Hindi replies | idle RSS ≤ 90 MB ✅ (64.0 MB measured, Linux); recognition only while speaking ✅; 464 tests green ✅; **live-mic accuracy needs one Windows verification pass** |
| **3 — Voice polish** | Piper first-run download UI, per-sentence streaming playback, interrupt/stop, voice preview in settings | first audio < 700 ms; both engines switchable from the UI (not just by voice) |
| **4 — Understanding** | Extend the rule grammar: timer, note, clipboard, volume/brightness, window control, file *search* | ≥ 95 % accuracy on the intent test corpus, < 5 ms/match |
| **5 — Memory** | history in SQLite, "yaad hai?" recall, settings persistence, per-user profile | history survives restart; DB stays < 5 MB after 10k turns |
| **6 — Thinking (optional LLM)** | llama.cpp child process, spawn/idle-kill lifecycle, Hindi prompt template | first token < 3 s on 4 CPU cores; RSS returns to idle after 60 s |
| **7 — Ship** | Nuitka build, Inno Setup installer, first-run model download, signing, release workflow | clean install on a fresh Win10 22H2 VM in < 3 min, works offline |

## Phase 2 carry-over

Phase 2 was built and tested on Linux with a fake microphone and a fake recogniser. These
items can only be confirmed on a real Windows 10 machine:

1. PortAudio capture from a real microphone and the device list in `--doctor`.
2. Real recognition accuracy of Vosk small-hi and IndicConformer on live Hindi/Hinglish.
3. Windows SAPI/OneCore synthesis (Hemant/Kalpana) and Piper playback through `winsound`.
4. Working-set size with the model loaded (expected 180–300 MB, budget 400 MB).
5. Whether the default VAD threshold suits typical Indian-room noise; 0.03–0.05 may be
   needed, which is why it is a config value rather than a constant.

Known limitations, by design:

* Power actions (shutdown/restart/sleep/lock) are recognised, confirmed and then
  **refused** — not implemented until the command layer has a longer track record.
* Only allowlisted targets can be opened: no arbitrary paths, URLs or applications.
* A recognised sentence is never fed to a shell, an interpreter, or the OS directly.

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

## Decisions taken in Phase 2

1. **Wake word without a wake model.** Instead of training openWakeWord, the VAD decides
   when a short burst happened and the existing ASR transcribes it; a fuzzy matcher looks
   for her name. One model instead of two runtimes, and nothing is ever always-on.
2. **Hinglish without transliteration.** Both Roman and Devanagari spellings are folded
   into the rule grammar (`kholo`/`खोलो`/`open`), so no IndicXlit model (~50 MB) is needed.
3. **Vosk is the default, sherpa-onnx is the upgrade.** 42 MB beats 130 MB on a 4 GB
   machine; `asr.engine` switches without touching any other code.
4. **Where the overlay lives.** Settled in Phase 1: a 566×486 rounded card, bottom-centre,
   draggable, remembered for the session.
