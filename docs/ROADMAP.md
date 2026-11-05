# Roadmap

Each phase ends with something you can run and measure. No phase starts before the
previous one meets its resource budget.

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Skeleton** ✅ | repo layout, config, logging, SQLite, `--doctor`, CI | `python -m shraddha --doctor` reports environment; tests green on Linux + Windows |
| **1 — Desktop interface** ✅ | Qt tray, floating overlay, global hotkey, single instance, chat, mic + text input | idle RSS ≤ 90 MB ✅ (61.8 MB measured, Linux); startup ≤ 2 s ✅ (176 ms); **needs one Windows verification pass** |
| **2 — Hearing (हिन्दी STT)** ✅ | PortAudio capture, energy VAD, Vosk small-hi (sherpa-onnx opt-in), wake word, mute, Hindi/Hinglish command layer, safety gates, Hindi replies | idle RSS ≤ 90 MB ✅ (64.0 MB measured, Linux); recognition only while speaking ✅; 464 tests green ✅; **live-mic accuracy needs one Windows verification pass** |
| **3 — Cloud intelligence (opt-in)** ✅ | Google Gemini via the official SDK, provider layer, key handling (env / Credential Manager), three-way consent gate, streamed answers in the chat, model fallback, Hindi error handling, doctor + CLI reporting | idle RSS ≤ 90 MB ✅ (64.4 MB measured, Linux); startup ≤ 2 s ✅ (200 ms); zero network before consent ✅; 615 tests green ✅; SDK imported lazily only on the worker ✅; **needs one Windows pass for the Credential Manager and a live key** |
| **3b — Voice polish** | Piper first-run download UI, per-sentence streaming playback, interrupt/stop, voice preview in settings | first audio < 700 ms; both engines switchable from the UI (not just by voice) |
| **4 — Understanding** | Extend the rule grammar: timer, note, clipboard, volume/brightness, window control, file *search* | ≥ 95 % accuracy on the intent test corpus, < 5 ms/match |
| **5 — Memory** | history in SQLite, "yaad hai?" recall, settings persistence, per-user profile | history survives restart; DB stays < 5 MB after 10k turns |
| **6 — Thinking (optional LLM)** | llama.cpp child process, spawn/idle-kill lifecycle, Hindi prompt template | first token < 3 s on 4 CPU cores; RSS returns to idle after 60 s |
| **7 — Ship** | Nuitka build, Inno Setup installer, first-run model download, signing, release workflow | clean install on a fresh Win10 22H2 VM in < 3 min, works offline |

## Phase 3 carry-over

Phase 3 was built and tested on Linux with a **fake Gemini client** - the suite never sets
`GEMINI_API_KEY` and never opens a socket. These items can only be confirmed on a real
Windows 10 machine with a real free-tier key:

1. `python -m shraddha --set-api-key` writing to, reading from, and deleting from the real
   Windows Credential Manager (`win32cred`, target `ShraddhaAI/GeminiApiKey`), including
   after a reboot and after a key rotation.
2. One live `--ai-check`: real latency, whether `gemini-flash-latest` resolves for a new
   project, and whether the `gemini-2.5-flash` fallback is served.
3. Real free-tier limits under repeated questions (429 / `RESOURCE_EXHAUSTED`) and the
   daily `quota` message.
4. Streaming smoothness in the Qt window with Nirmala UI shaping while chunks arrive.
5. Working-set size with the SDK imported and a request in flight (expected +15–25 MB).

Deliberate limitations of this phase:

* **Gemini only.** The provider protocol (`ai/base.LlmProvider`) is the seam for future
  providers; `llm.provider = "local"` is validated and reserved for Phase 6.
* **No function calling, no tools, no code execution.** The model cannot ask the app to do
  anything, by design and by test.
* **One request at a time.** A question asked while an answer is streaming is answered
  locally rather than queued.
* **Answers are not stored in the AI history** beyond `llm.history_turns` exchanges in
  memory; the chat transcript in SQLite is unchanged from Phase 1.

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

## Decisions taken in Phase 3

1. **Cloud AI is a fourth gate, not a setting.** A single `llm.enabled` switch invites
   accidents; requiring *provider + key + in-app consent* means a stray config edit cannot
   upload anything. Every request re-checks the gate, so revoking consent is immediate.
2. **`gemini-flash-latest` with one fallback.** Aliases move and models get retired; a
   404 retries once with `gemini-2.5-flash`, and only before any text is shown, so a
   partial answer is never duplicated.
3. **A new `shraddha.ai` package, not code in `assistant.py`.** `ai/` is forbidden from
   importing `commands` or `subprocess`, which is what makes "the model can never act"
   a structural fact instead of a promise.
4. **Streaming with one bubble.** Chunks append to a single `MessageBubble` and the reply
   is spoken once at the end; per-chunk TTS would stutter Hindi mid-sentence.
5. **The SDK is imported on the worker, on first use.** If a user never consents, the
   process behaves exactly as it did in Phase 2 (measured: +0.4 MB idle, +16 ms startup
   for the whole AI layer).
6. **Keys live outside the config.** Environment variables first, then the Windows
   Credential Manager via the `win` extra that already exists — no new dependency, and
   `config.json` can be shared safely.

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
