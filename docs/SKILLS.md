# Everyday skills (Phase 4) — timer, notes, clipboard, volume, windows, file search

> Six skills that make the assistant useful without a language model. All of them are
> **local**, all of them are **rule-based** (no model, no key, no network), and the
> destructive ones ask first.

---

## 1. What you can say

| Skill | Say this | What happens |
|---|---|---|
| **Timer** | "5 मिनट का टाइमर लगाओ", "30 second ka timer", "1 ghanta 30 minute ka timer" | announces when it fires: chat message + Hindi speech + tray notification |
| | "टाइमर कितना बाकी है" | remaining time in words ("लगभग 4 मिनट बाकी") |
| | "टाइमर बंद करो", "timer cancel" | cancels it |
| **Notes** | "नोट लिखो दूध लाना है", "note likho kal meeting hai" | stored in SQLite (`notes` table), survives restart |
| | "मेरा नोट पढ़ो", "notes batao" | last 5 notes, numbered newest-first |
| | "नोट साफ़ करो" | **asks first**, then deletes |
| **Clipboard** | "copy karo बैठक 5 बजे", "क्लिपबोर्ड में डालो …" | puts that text on the clipboard |
| | "clipboard kya hai", "क्लिपबोर्ड में क्या है" | reads it back (truncated at 500 characters) |
| **Volume** | "volume बढ़ाओ", "आवाज़ कम करो", "volume mute karo" | relative steps / mute (Windows media keys, ≈10 % per "badhao") |
| | "volume 40 karo" | **honestly refused** — see limitations |
| **Windows** | "window छोटा करो", "window minimize karo" | minimises the foreground window |
| | "window बंद करो" | **asks first**, then sends `WM_CLOSE` (a polite close, not a kill) |
| **File search** | "documents में budget ढूँढो", "downloads mein report dhundo" | lists matching file names; never opens, never executes |

Everything from Phases 1–3 keeps working exactly as before: open apps/folders/sites,
date/time, stop listening, voice switching, and the optional cloud answer.

---

## 2. Where the code lives

```
commands/router.py   pure text -> intent   (parse_timer / parse_note / parse_clipboard /
                                            parse_volume / parse_window / parse_search)
commands/timer.py    AlarmTimer: one timer, threading.Timer (daemon), Hindi duration words
commands/actions.py  the only module that may call the OS (clipboard, keys, windows),
                     plus notes wiring, the bounded file walk, and every refusal
storage/db.py        notes table (already existed) + delete_notes()
ui/timer.py          TimerBridge: timer thread -> Qt signal -> GUI thread
ui/app.py            wires the skills into the ActionExecutor and announces fired timers
```

The router stays **pure**: it never arms a timer or reads a clipboard, which is why 42
routing tests run in 0.3 s without mocking a single OS call.

---

## 3. Safety rules

1. **Every OS dependency is injected.** `ActionExecutor` takes `clipboard_read`,
   `clipboard_write`, `volume_control`, `window_control`, `timer`, `notes_*` and
   `search_roots`. In tests they are fakes, so nothing is pressed, closed or copied.
2. **No shell, no new process for these skills.** Volume uses the documented media keys
   (`VK_VOLUME_UP/DOWN/MUTE`), windows use `ShowWindow`/`PostMessage`, the clipboard uses
   `win32clipboard`. Nothing is interpolated into a command line.
3. **Destructive commands ask.** "नोट साफ़ करो" and "window बंद करो" both route with
   `needs_confirmation=True`, so the existing `ConfirmationGate` asks "हाँ / नहीं" first.
   Silence is never consent.
4. **Search is bounded and read-only.** Depth ≤ 4, `node_modules`/`.git`/`AppData`/… are
   skipped, at most 12 matches, and the results are only *named* in the chat.
5. **Honest refusals.** On Linux/macOS the clipboard, volume and window skills answer
   "यह सुविधा इस सिस्टम पर उपलब्ध नहीं है - यह Windows पर काम करती है।" rather than
   failing silently or pretending.

---

## 4. Threading

```
phrase ─► router (GUI thread, <1 ms) ─► ActionExecutor ─► AlarmTimer.start()
                                                              │
                                        threading.Timer (daemon)
                                                              ▼
                                        TimerBridge.fired  ──queued Qt signal──►
                                        controller.on_timer_fired()  (GUI thread)
                                          └─ chat message + Hindi speech + tray balloon
```

* `AlarmTimer` uses one `threading.Timer`, **daemonised** so a pending timer can never
  keep the process alive after quit; `shutdown()` cancels it.
* Only one timer exists at a time — arming a new one cancels the old and says so
  ("पिछला टाइमर हटाकर …").
* The announcement crosses threads through a Qt signal, so widgets are only touched on the
  GUI thread.

---

## 5. Deliberate limitations

| Limitation | Why |
|---|---|
| Absolute volume ("volume 40 karo") is recognised but refused | It needs the Core Audio COM interface; the relative-key path is documented and testable, a half-working COM call is not. The refusal names the commands that do work. |
| "mute karo" mutes the **microphone**, "volume mute karo" mutes the speakers | Microphone mute existed in Phase 2 and must not silently change meaning; the speaker variant requires an explicit "volume"/"आवाज़" word. |
| File search matches names literally | "बजट" matches `बजट-2026.xlsx`, not `budget-2026.xlsx`. Transliteration would need an extra model; the search is documented as literal, in either script. |
| Window commands act on the **foreground** window | Targeting a specific window by name needs enumeration and a picker; not in this phase. |
| No "paste into the active app" | Paste means focusing another app and typing into it — the riskiest thing this assistant could do, so it stays out. |

---

## 6. Verification

**Tested automatically (Linux sandbox):** 106 new tests —
`tests/test_router_phase4.py` (42: sentences, near misses, duration parsing, <5 ms/match),
`tests/test_timer.py` (18: arm/replace/fire/cancel/status, daemon default),
`tests/test_actions_phase4.py` (31: every skill with fakes, every refusal, bounded search,
dry-run), `tests/test_ui_skills.py` (15: controller end-to-end, confirmation round-trips,
persistence, shutdown). Full suite: **721 passed**, `ruff` clean.

**Not verified here — needs Windows 10:**

1. `win32clipboard` read/write against real clipboard contention (an app holding the
   clipboard open raises, and the handler reports it).
2. Media-key volume steps on real hardware, and whether 5 presses ≈ 10 % on your machine.
3. `ShowWindow(SW_MINIMIZE)` / `WM_CLOSE` behaviour with elevated or full-screen windows.
4. Tray balloon delivery for a fired timer with the overlay hidden.
5. Hindi speech of the announcement through OneCore/Piper.

Nothing in this document claims those were tested on Windows.
