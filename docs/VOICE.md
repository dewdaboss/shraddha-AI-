# Hindi voice recognition and voice commands (Phase 2)

Everything in this document runs on your own computer. There is no API key, no account,
no upload, and no subscription. Unplug the network cable and it still works.

> **What was actually tested, and what was not.** All logic below is covered by automated
> tests that run on Linux CI with a *fake* microphone and a *fake* recogniser. The real
> audio path (PortAudio, the Windows microphone, the Vosk/IndicConformer models and the
> Windows voices) cannot be executed in the development sandbox, so it is reported as
> **hardware-dependent** wherever it appears. See [Verification](#12-verification-what-is-tested-and-what-is-not).

---

## 1. What Phase 2 adds

| Capability | Status |
|---|---|
| Offline Hindi/Hinglish speech recognition, loaded only when needed | ✅ implemented, model download verified, no live mic test |
| Voice activity detection in pure Python (no numpy, no ONNX) | ✅ tested with synthetic audio |
| Push-to-talk, optional "श्रद्धा" wake word, mute/unmute | ✅ tested |
| Hindi + Hinglish command understanding (open app / folder / site, date, time, stop listening, change voice) | ✅ tested |
| Safety layer: allowlists, no shell, confirmation for sensitive actions | ✅ tested |
| Hindi spoken replies through the existing TTS architecture, with voice switching | ✅ logic tested, synthesis is Windows/Piper-dependent |
| Recognised text in the chat transcript, live status line, clear errors | ✅ tested (headless Qt) |
| Idle model unloading (ASR freed after 120 s of silence) | ✅ tested with a fake clock |
| Always-on heavy model | ❌ never — by design |

Not in this phase: answering open-ended questions (needs the Phase 6 local LLM), system
volume/brightness, file *search* by name, and any command that is not in the allowlist.

---

## 2. The pipeline

```
 microphone (16 kHz, mono, 20 ms frames)
        │  PortAudio callback thread: queue only, never blocks
        ▼
   Ring of frames ──► EnergyVad ──► VadSegmenter ──────► utterance (PCM)
                        │                │                    │
                   noise floor      silence = end     worker thread only
                                                     ▼
                                             ASR (loaded on demand)
                                                     ▼
                                          transcript (Hindi/Hinglish)
                                                     ▼
                              WakeWordMatcher (only in "phrase" mode)
                                                     ▼
                                   CommandRouter  ──► Command(intent, args, spoken)
                                                     ▼
                            ConfirmationGate (sensitive actions only)
                                                     ▼
                                     ActionExecutor (allowlist, shell=False)
                                                     ▼
                                       Hindi reply ──► chat + TTS
```

Threads, and why:

| Thread | Owns | Never does |
|---|---|---|
| GUI (Qt) | widgets, signals, status line | opens the microphone, loads a model |
| `shraddha-voice` worker | `VoiceService`, VAD, **ASR**, idle unload | touches a widget |
| PortAudio callback | pushing bytes into a `queue.Queue` | blocking, allocating, importing |

A model load takes 1–3 s; the decode after you stop speaking takes about 0.2–1 s on a
4-core laptop. Both happen on the worker, so the window never freezes and never shows
"Not responding".

---

## 3. Which recognition engine, and why

| Engine | Model size | Licence | Idle RAM while loaded | Verdict |
|---|---|---|---|---|
| **Vosk `vosk-model-small-hi-0.22`** (default) | 42 MB | Apache-2.0 | ~100–200 MB | ✅ **Chosen.** Smallest credible Hindi model, one `pip install vosk`, no ONNX Runtime, supports a grammar for the wake path, runs on a 4 GB machine. |
| sherpa-onnx + IndicConformer Hindi `int8` (opt-in) | ~130 MB | CC-BY-4.0 | +60–90 MB ONNX Runtime | ✅ **Supported.** Noticeably better on accented/noisy speech; costs one more wheel and more RAM. Select with `asr.engine = "sherpa"`. |
| whisper.cpp (base/small) | 75 MB–1.5 GB | MIT | 300 MB–2 GB | ❌ Rejected: heavier, slower on CPU, no streaming, and the Hindi quality gain does not justify 4–10× the RAM. |
| Meta MMS-TTS / VITS via PyTorch | ~420 MB per process | CC-BY-NC | 400 MB+ | ❌ Rejected: **PyTorch** alone is ~800 MB of wheel and ~250 MB RSS before a single word. Explicitly out of bounds. |
| openWakeWord (dedicated wake model) | ~5 MB | Apache-2.0 | small | ❌ Rejected for now: a second neural runtime for one phrase; the VAD + short-burst ASR path already works and shares one model. |
| Cloud ASR (Google/Azure/Whisper API) | — | — | — | ❌ Rejected: paid, online, and uploads your voice. |

The decision lives in code, in `src/shraddha/speech/engines/__init__.py`, with the same
table as a docstring. `create_recognizer("auto")` tries Vosk first, then sherpa-onnx, and
returns `None` (not an exception) when neither can run — the UI then explains what to do.

### Installing the models

```bash
pip install -e ".[ui,audio,asr-vosk]"        # Qt + microphone + Vosk
python scripts/fetch_models.py --set asr-light   # 42 MB, Apache-2.0, auto-unzips
python -m shraddha --doctor                  # must show "engine vosk ... ready"
```

Better accuracy, ~130 MB more RAM:

```bash
pip install -e ".[ui,audio,asr]"             # adds sherpa-onnx (~60 MB wheel)
python scripts/fetch_models.py --set asr-main
```

Models land in `%LOCALAPPDATA%\SHRADDHA AI\models` and are never committed: the
repository stays tiny, and the download is checksum-verifiable.

---

## 4. The wake word

Three modes, set in `config.json` under `wake.mode`:

| Mode | Behaviour | Cost |
|---|---|---|
| `push_to_talk` (default) | Nothing is recorded until you press the mic button. | Zero while idle. |
| `phrase` | The microphone stays open; the assistant only reacts after hearing her name. | One small model, kept loaded for `wake.idle_unload_s` (60 s) after the last utterance. |
| `off` | Voice input is disabled entirely. | Zero. |

There is **no always-on large model**. In `phrase` mode the VAD decides when a burst of
speech happened, and only that short burst (typically 0.3–2 s) is transcribed. Between
bursts the recogniser is idle; if nothing is said for a minute it is unloaded completely.

Matching is deliberately forgiving, because ASR spelling of Hindi names is unstable:

* Latin spellings accepted: `shraddha`, `shradha`, `sraddha`, `shardha`, `shrddha`, `shradhdha`
* Devanagari spellings accepted: `श्रद्धा`, `श्रद्घा`, `सृद्धा`
* Fillers before the name are ignored: `hey`, `arre`, `suno`, `अरे`, `सुनो`…
* A bounded Levenshtein distance (`wake.fuzzy_distance`, default 2) catches the rest.
* A word that merely *contains* the name (`shraddhachrome`) does **not** wake her.
* Changing `wake.phrases` renames her — the built-in spellings only apply to names you
  actually configured.

The name plus the command in one breath is handled properly:
`"श्रद्धा, Chrome खोलो।"` → wake + command `chrome खोलो`. After waking, an 8-second window
lets you follow up without repeating the name.

Stopping her: **"श्रद्धा, मेरी बात सुनना बंद करो।"**, "सुनना बंद करो", "stop listening",
"sunna band karo" or "mute" — this mutes the microphone and says so.

---

## 5. Voice commands

Everything is matched against a fixed catalogue, in Hindi, Hinglish or a mix of both.
Spelling variants are folded (`normalise_name`), so `kholo` / `खोलो` / `open` / `launch`
/ `चालू` all mean the same thing.

| You say | Intent | What happens |
|---|---|---|
| "श्रद्धा, Chrome खोलो।" · "chrome khol do" · "क्रोम खोलो" | `app.open` | Chrome launches, no shell involved |
| "श्रद्धा, Arena AI खोलो।" · "arena open karo" | `web.open` | `https://arena.ai` in your default browser |
| "नोटपैड खोलो" · "notepad kholo" | `app.open` | Notepad |
| "कैलकुलेटर खोलो" · "calculator open karo" | `app.open` | Calculator |
| "सेटिंग्स खोलो" · "settings kholo" | `app.open` | Settings |
| "vscode kholo" · "paint kholo" · "files kholo" | `app.open` | VS Code, Paint, Explorer |
| "श्रद्धा, मेरी डाउनलोड फाइल खोलो।" · "downloads kholo" | `folder.open` | Downloads (resolved from Windows' own folder registry) |
| "documents kholo" · "desktop kholo" · "pictures kholo" · "music kholo" | `folder.open` | that known folder |
| "श्रद्धा, आज की तारीख बताओ।" · "aaj ki tarikh kya hai" | `info.date` | answered from the system clock |
| "समय क्या है?" · "kitne baje hain" | `info.time` | answered from the system clock |
| "आवाज़ बदलो" · "next voice" · "दूसरी आवाज़" | `voice.switch` | cycles the spoken voice and remembers it |
| "श्रद्धा, मेरी बात सुनना बंद करो।" | `voice.stop` | mutes the microphone |
| "कंप्यूटर बंद करो" · "shutdown karo" | `system.power` | **refused** (see §6) |
| anything else | `unknown` | answered by the chat layer, never executed |

An app that is not in the catalogue gets an honest answer, not a guess:
*"मुझे यह नहीं पता कि इसे कैसे खोलना है। मैं केवल तय सूची में से खोल सकती हूँ…"*

---

## 6. Safety

Speech recognition makes mistakes. The design assumes it will.

1. **Nothing spoken ever becomes a shell command.** `ActionExecutor` resolves the intent
   against `APP_CATALOG` / `WEB_ALLOWLIST` / `FOLDER_ALIASES` and calls
   `subprocess.Popen([exe], shell=False)`. There is no string interpolation into a shell
   anywhere in the codebase.
2. **Paths in the transcript are ignored.** "downloads kholo" is resolved from the
   Windows *User Shell Folders* registry value. If a transcript contains
   `C:\Windows\System32\cmd.exe`, the router sees an unknown app and refuses.
3. **URLs are an allowlist, matched exactly.** `https://arena.ai` opens;
   `https://example.com`, `javascript:…`, `file:///…` and a case-shifted duplicate are
   refused.
4. **Sensitive actions need a spoken yes.** With `commands.allow_power_actions = true`
   the router asks *"क्या आप सच में कंप्यूटर बंद करना चाहते हैं? 'हाँ' या 'नहीं' कहिए।"*
   Only an explicit approval runs it. "शायद", a cough, or an unrelated sentence leaves
   the question open — never treated as consent.
5. **Power actions are not implemented at all.** Even after a "yes", Phase 2 refuses with
   *"…अभी समर्थित नहीं है।"* An assistant that can be talked into shutting down a machine
   is a liability while recognition is imperfect.
6. **Recognition is bounded.** Only allowlisted targets, a 15-second maximum utterance,
   and a minimum speech length (250 ms) so a door slam is not a command.

---

## 7. Spoken replies

`tts.speak_replies` (default `true`) speaks every reply, using the architecture from
Phase 1 and the voice you already selected:

| Engine | Voice | Licence | When |
|---|---|---|---|
| Windows (SAPI/OneCore) | **Hemant** (male) or **Kalpana** (female), once Hindi is added in Settings → Time & Language | with Windows, ✅ commercial use | default, instant, no download |
| Piper `hi_IN` (optional) | `priyamvada` / `pratham` / `rohan` | **non-commercial** (CC-BY-NC-SA training data) | `pip install -e ".[tts-piper]"` + `fetch_models.py --set tts-piper` |
| none | — | — | `tts.engine = "none"`: text only |

Say "आवाज़ बदलो" to cycle through the available voices; the choice is written back to
`config.json`. Every synthesis call is wrapped: a dead COM apartment or a missing model
degrades to silence plus a log line, never to a crash mid-sentence.

### Installing a Hindi voice on Windows 10

1. Settings → Time & Language → Language → **Add a language** → हिन्दी (Hindi).
2. Tick **Speech** (it installs Hemant and Kalpana) and let Windows finish.
3. `python -m shraddha --doctor` — the TTS section must show a Hindi voice.

---

## 8. Resource behaviour

Measured on this project's sandbox (Linux, Qt `minimal` platform, **no model installed**):

| Metric | Value |
|---|---|
| Startup to a ready window | **184 ms** |
| Idle resident set | **64.0 MB** (Phase 1 was 62 MB; the voice layer costs ~2 MB) |
| Background processes | 0 |
| Working threads when idle | 1 GUI thread (the voice worker exists only while listening) |

Expected on a Windows 10 laptop with the small Hindi model loaded:

| State | Expected RSS |
|---|---|
| Idle, nothing listening (`push_to_talk`) | 60–80 MB |
| Listening, Vosk small-hi loaded | 180–300 MB |
| Listening, IndicConformer int8 (opt-in) | 300–450 MB |
| Above + Piper voice | add ~90 MB per synthesis |

Budgets for the whole project stay: idle < 90 MB, voice < 400 MB, +Piper < 500 MB.

Idle unloading: `asr.idle_unload_s` (default 120 s) frees the model after the last
utterance, and `wake.idle_unload_s` (default 60 s) does the same in wake mode. The tick
runs on the voice worker, so unloading costs nothing on the GUI thread.

---

## 9. Configuration reference (`config.json`, schema 2)

```jsonc
{
  "schema_version": 2,
  "log_level": "INFO",
  "audio": {
    "sample_rate": 16000, "channels": 1, "frame_ms": 20,
    "device": null            // PortAudio input device; null = system default
  },
  "asr": {
    "engine": "auto",         // auto | vosk | sherpa | none
    "model_dir": null,        // null = <app home>/models
    "language": "hi",
    "num_threads": 2,
    "device": null,
    "sample_rate": 16000,
    "vad_threshold": 0.02,    // the speech gate (0.03-0.05 in a noisy room)
    "min_speech_ms": 250,     // shorter bursts are clicks, not words
    "silence_ms": 700,        // end of utterance
    "max_utterance_ms": 15000,
    "idle_unload_s": 120      // free the model after this much silence (0 = never)
  },
  "wake": {
    "mode": "push_to_talk",   // push_to_talk | phrase | off
    "phrases": ["hey shraddha", "श्रद्धा", "shraddha", "o shraddha"],
    "fuzzy_distance": 2,
    "idle_unload_s": 60
  },
  "commands": {
    "enabled": true,
    "allow_power_actions": false,   // still refused at the OS layer
    "confirm_sensitive": true,
    "announce_actions": true
  },
  "tts": {
    "engine": "auto",         // auto | onecore | piper | none
    "voice": null,            // Windows voice name or Piper model stem
    "rate": 0,                // -10..10
    "volume": 100,            // 0..100
    "piper_model": null,      // explicit path to a .onnx; null = search models/
    "speak_replies": true
  },
  "ui": { "hotkey": "ctrl+alt+s", "language": "hi", "overlay": true,
          "start_minimised": false, "always_on_top": true },
  "llm": { "enabled": false }   // Phase 6
}
```

Invalid values are rejected with a specific message instead of being silently accepted:
`AppConfig.load()` and `--doctor` both refuse a wake mode of `always`, a `silence_ms`
below 100, a negative `idle_unload_s`, and so on. Unknown keys are ignored, so a config
written by an older version still loads.

---

## 10. Using it

1. Start the assistant: `python -m shraddha --ui` (or the tray icon).
2. Press **Ctrl+Alt+S** to show the window.
3. Click the **microphone button** (or press it again to stop) and speak.
   In `phrase` mode you can instead just say "श्रद्धा, …".
4. Watch the status line under the chat:
   * `तैयार — आवाज़ के लिए माइक दबाइए` (ready)
   * `सुन रही हूँ… बोलिए` (listening, with a live partial transcript on the right)
   * `सोच रही हूँ…` (decoding)
   * `माइक्रोफ़ोन म्यूट है` (muted)
   * a red line when something is wrong, plus the same sentence in the transcript
5. The **crossed-microphone button** mutes/unmutes; mute is remembered for the session.
6. Every recognised sentence appears in the chat as a normal user message, followed by
   the assistant's Hindi reply — and it is stored in SQLite like typed messages.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `आवाज़ से सुनना उपलब्ध नहीं: microphone support is not installed…` | `sounddevice` is missing | `pip install -e ".[audio]"` (on Linux also `apt install libportaudio2`) |
| `हिन्दी Vosk मॉडल नहीं मिला…` | model not downloaded | `python scripts/fetch_models.py --set asr-light` |
| `हिन्दी IndicConformer मॉडल नहीं मिला…` | `asr.engine = "sherpa"` without the model | `fetch_models.py --set asr-main`, or set `asr.engine = "auto"` |
| Everything transcribes as unrelated words | wrong input device (e.g. a virtual cable) | set `asr.device` to your microphone index (`--doctor` lists devices) |
| She wakes on her own | noisy room, threshold too low | raise `asr.vad_threshold` to 0.03–0.05 |
| The end of a sentence is cut off | `silence_ms` too short for your pause style | raise `silence_ms` to 900–1200 |
| Replies are silent | no Hindi voice installed, or `tts.engine` is not usable | install the Hindi speech feature, then `--doctor`; or `fetch_models.py --set tts-piper` |
| Piper replies are silent | `piper-tts` missing or model absent | `pip install -e ".[tts-piper]"` and fetch `tts-piper` |
| Recognition is slow (>2 s) | `num_threads` too high on a 2-core machine, or a large model | set `asr.num_threads = 2`, or switch to Vosk |

`python -m shraddha --doctor` reports the microphone, both engines, the model location,
the wake mode and the TTS engine, with the exact command to fix anything missing.

---

## 12. Verification: what is tested, and what is not

**Tested automatically** (466 tests, pytest, ~2 s in this sandbox; 269 of them added in
Phase 2):

* VAD on synthetic audio: speech vs silence, click rejection, max-utterance cut, pre-roll,
  flush-on-release — no microphone needed.
* Segmentation driving the service: speech → one utterance → one transcript.
* Wake matching: Latin and Devanagari spellings, filler words, mispronunciations, and
  non-matches (`shraddhachrome`, ordinary sentences, custom names).
* Command corpus: 40+ Hindi/Hinglish sentences per intent, ordering invariants
  (stop-listening beats power, date beats time), unknown-target refusal.
* Safety: non-allowlisted URL, unknown app, injected path, `shell=False` argv, a
  `Popen` that raises, zip-slip in the model fetcher.
* Confirmation: yes/no/unclear in Hindi, English and Hinglish; one-shot approval.
* Mute/unmute, mode switching, the awake window, idle model unload with a fake clock.
* Missing model, model that fails to load, failing decode, missing microphone — each with
  the exact user-facing Hindi string.
* Qt wiring: service events → signals → status line, chat bubbles, mute button icon.
* Persistence of recognised turns and the smooth coexistence with typed chat.
* Existing Phase 0/1 behaviour: all 197 earlier tests still pass (three of them were
  updated because the microphone button now really listens).

**Not tested here — needs your Windows machine** (the sandbox has no microphone, no sound
device and no GPU):

* The real PortAudio capture path and device enumeration on Windows.
* Actual recognition accuracy of Vosk small-hi and IndicConformer on your accent/room.
* Windows SAPI/OneCore synthesis in Hemant/Kalpana, and Piper playback via `winsound`.
* `RegisterHotKey` and tray behaviour (headless Qt cannot show a tray).
* Devanagari shaping of the new status strings in the real Windows font stack.

The first three are the ones to try first: press the microphone, say
"श्रद्धा, Chrome खोलो।", and check both the transcript and whether Chrome opens. If the
transcript is wrong, raise `asr.vad_threshold` slightly and try again before switching
engines — in most rooms the VAD default is the difference between 60% and 90% accuracy.

---

## 13. Design notes

* **Why not keep the model loaded?** 42 MB of weights becomes 150–250 MB of resident
  memory once Kaldi allocates its graphs. On a 4 GB machine that is the difference between
  "usable next to a browser" and "swapping".
* **Why an energy VAD instead of Silero?** Silero is better, but it needs ONNX Runtime
  (~60 MB) plus PyTorch/librosa tooling to export. `EnergyVad` is 40 lines of pure Python,
  adaptive, and tested; the recogniser itself is the second stage of filtering.
* **Why two engines?** Machines differ. Vosk respects a 4 GB budget; IndicConformer is
  what you switch to when you have 8 GB and a noisy room. Both talk to the same
  `OfflineRecognizer` protocol, so nothing above the engine changes.
* **Why is `commands/` separate from `speech/`?** Recognition produces text; commands
  produce *actions*. Keeping the two apart is what makes "never execute recognised speech
  directly" checkable in code review: `speech/` cannot import `subprocess`.
