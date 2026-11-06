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
| **4 — Everyday skills** ✅ | timer, notes, clipboard, relative volume, window minimise/close (confirmed), bounded file search; honest refusals where a platform cannot do it | 42-sentence intent corpus green ✅; **< 0.2 ms/match measured** (budget 5 ms) ✅; 721 tests green ✅; idle RSS 64.5 MB ✅; startup 228 ms ✅; **clipboard/volume/window APIs need one Windows pass** |
| **5 — Memory** | history in SQLite, "yaad hai?" recall, settings persistence, per-user profile | history survives restart; DB stays < 5 MB after 10k turns |
| **6 — Thinking (optional LLM)** | llama.cpp child process, spawn/idle-kill lifecycle, Hindi prompt template | first token < 3 s on 4 CPU cores; RSS returns to idle after 60 s |
| **7 — Ship** | Nuitka build, Inno Setup installer, first-run model download, signing, release workflow | clean install on a fresh Win10 22H2 VM in < 3 min, works offline |

## Phase 4 carry-over

Phase 4 was built and tested on Linux with injected fakes: no clipboard was opened, no key
was pressed and no window was closed. These items can only be confirmed on Windows 10:

1. `win32clipboard` read/write, including when another app holds the clipboard open (the
   handler reports it instead of crashing).
2. Media-key volume steps on real hardware — and whether 5 presses ≈ 10 % there.
3. `ShowWindow(SW_MINIMIZE)` and `WM_CLOSE` against normal, elevated and full-screen
   windows (a crashed app may show the "this program is not responding" dialog).
4. Tray balloon delivery for a fired timer while the overlay is hidden.
5. Hindi speech of the timer announcement through OneCore/Piper.

Deliberate limits from this phase (documented, not bugs):

* absolute volume ("volume 40 karo") is recognised and honestly refused — no Core Audio
  COM call is shipped untested;
* "mute karo" still means the microphone; speaker mute needs the word "volume"/"आवाज़";
* file search matches names literally, so "बजट" does not match `budget.xlsx`;
* window commands act on the foreground window only, and there is no "paste into the
  active app" (that is the riskiest possible command).

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

## Decisions taken in Phase 4

1. **A separate `commands/timer.py`, not a thread inside `ui/app.py`.** The timer is
   logic (arm, replace, fire, cancel) and belongs with the other pure pieces; the Qt
   signal is a thin bridge. It also makes the threading rule explicit: the callback runs
   on the timer thread, the widgets are only touched after the queued signal.
2. **Every skill takes an injected callable.** `ActionExecutor` gained `clipboard_read`,
   `volume_control`, `window_control`, `timer`, `notes_*` and `search_roots`. That is why
   31 action tests can prove the decisions without pressing a single key.
3. **Destructive = confirmed.** Notes are data and windows hold unsaved work, so both
   "नोट साफ़ करो" and "window बंद करो" reuse the Phase 2 confirmation gate.
4. **Refuse what cannot be done well.** Absolute volume and cross-app paste are named in
   the reply and in this document instead of being shipped half-working.
5. **Search is bounded, never executes.** Depth ≤ 4, noise directories skipped, ≤ 12
   results, names only — a spoken search must not become a file browser.
6. **Daemon timer.** A pending timer must never keep the process (or a test run) alive.

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
