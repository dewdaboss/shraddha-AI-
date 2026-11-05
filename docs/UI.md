# Interface

Phase 1 delivered the shell: a tray icon, a floating overlay, a global hotkey and a text
command loop. Phase 2 connects the microphone for real and adds a status line, a live
partial transcript and a mute control. The voice pipeline itself is documented in
[VOICE.md](VOICE.md); this file is about what the user sees and touches.

When voice input cannot work — no sounddevice, no model, no microphone — the interface
says so in Hindi in the transcript and on the status line, instead of faking a transcript.

## What the user sees

```
┌──────────────────────────────────────────── 566 x 486, rounded 22px ─┐
│ ●  SHRADDHA                          [CTRL+ALT+S]  ✕                │
│    हिन्दी सहायक · पूर्णतः ऑफ़लाइन                                     │
│                                                                      │
│  ┌────────────────────────┐                                          │
│  │ नमस्ते! मैं श्रद्धा हूँ। │                       ┌────────────────┐ │
│  └────────────────────────┘                       │ क्रोम खोलो      │ │  ← user: green tint
│                                                   └────────────────┘ │
│  ┌────────────────────────┐                                          │
│  │ Chrome खोल रही हूँ।      │                                          │
│  └────────────────────────┘                                          │
│  सुन रही हूँ… बोलिए                          क्रोम खो…                 │  ← status · partial
│  ( ⃠ )  ( ◉ )  [ हिन्दी में लिखिए… ]                            ( ➤ ) │
└──────────────────────────────────────────────────────────────────────┘
   mute    mic
```

## Interactions

| Action | Result |
|---|---|
| `Ctrl+Alt+S` anywhere | show / hide the overlay |
| Tray icon click | show / hide the overlay |
| Tray → Open / Clear chat / Quit | the menu |
| `Enter` in the input | send |
| `Esc` | hide the overlay (the app keeps running) |
| Drag the header | move the window; remembered for the session |
| Microphone button | start / stop listening (push-to-talk) |
| Crossed-microphone button | mute / unmute; the icon and the status line both change |
| Saying "सुनना बंद करो" | mutes the microphone and says so |
| Any recognised sentence | appears as a normal user bubble, is answered and spoken |
| Close the overlay | hides it; quitting is only via the tray |

Nothing in the UI ever quits the assistant except **Quit**: hiding a window is not exit,
and that distinction is what lets the hotkey feel instant forever.

## Voice states on screen

| State | Status line | Dot | Notes |
|---|---|---|---|
| idle | `तैयार — आवाज़ के लिए माइक दबाइए` | dim | nothing is recorded |
| listening | `सुन रही हूँ… बोलिए` | neon | partial transcript appears on the right |
| decoding | `सोच रही हूँ…` | neon | ASR runs on the worker thread |
| muted | `माइक्रोफ़ोन म्यूट है` | dim | crossed-microphone icon is checked |
| wake mode armed | `श्रद्धा कहकर बुलाइए` | neon | no model is decoding between bursts |
| error | the first line of the error, red | dim | the full sentence also lands in the chat as a system message |

The status line is a `QLabel` with a `state` property (`idle` / `listening` / `muted` /
`error`) styled from the theme's QSS, so the colours stay in one place.

## Design tokens

| Token | Value | Use |
|---|---|---|
| `background` | `#050706` | near-black canvas |
| `surface` / `surface_raised` | `#0A0D0B` / `#101512` | input field, cards |
| `neon` | `#00FF9C` | the single accent: focus, user bubble border, active mic |
| `neon_dim` | `#00C77A` | idle dot, hover |
| `text` / `text_dim` / `text_faint` | `#E9F6F0` / `#84968C` / `#5A6B62` | primary / secondary / tertiary |

Rules: **one** accent colour, no drop shadows, no gradients heavier than a two-stop
`QLinearGradient`, radii 15–22 px, and motion capped at 170 ms. Tokens live in
`src/shraddha/ui/theme.py` and are unit-tested (including "exactly one neon accent").

## Hindi text

The font stack is `Nirmala UI → Noto Sans Devanagari → Mangal → Segoe UI → DejaVu Sans`.
Nirmala UI ships with Windows 10 and is what Windows itself uses for Devanagari, so
conjuncts and matras shape correctly without bundling a font file. The stack is applied to
`QWidget` globally, so Hindi is correct even in the menu and tooltips.

Text is set as `Qt.TextFormat.PlainText`. That is both a performance choice (no markup
parser) and a safety one (a message containing `<` cannot inject HTML).

## Performance decisions

| Decision | Why |
|---|---|
| Widgets, not QML/QtQuick | the QML engine and a scene graph cost tens of MB; QWidget does not |
| Icons drawn with `QPainter` | no image files, sharp at any DPI, recolours with the theme |
| Bubbles capped at 200 | a session left open for days cannot grow the widget tree |
| Animations only while needed | the mic pulse loop stops when unchecked; the overlay fade only runs on show/hide |
| Opacity animation skipped on headless plugins | avoids a warning per frame under `minimal`/`offscreen` |
| One `QApplication`, zero extra processes | no helper daemon, no IPC beyond a single local socket |
| Qt imported only by `--ui` | `--doctor`, `--init` and the tests stay under ~45 ms of imports |

Measured on the development sandbox (Linux, Qt `minimal` platform, no fonts, no GPU):

| Metric | Value |
|---|---|
| import core (`doctor`, `config`, `storage`) | ~43 ms |
| import Qt UI | ~43 ms |
| spawn → UI ready | **176 ms** |
| resident memory while idle | **61.8 MB** (210 samples, median = peak) |

`python scripts/measure_resources.py` reproduces this on any machine, including Windows.

## What could not be verified on Linux

Be explicit about the gap between "tested" and "assumed":

| Area | Status |
|---|---|
| Widget construction, layout, signals, chat, trimming, state machine | **tested** (197 tests, headless Qt) |
| Painting (border, gradients, bubbles) | **tested** structurally; colours verified by pixel probing |
| Devanagari shaping and typography | **not verified** — the sandbox has no font with Devanagari coverage, so text renders as placeholder boxes |
| `RegisterHotKey` + `WM_HOTKEY` delivery | **not verified** — Windows-only API; parsing is tested, registration is not |
| System tray icon, menu, balloon | **not verified** — `QSystemTrayIcon` is unavailable headless; the degradation path is tested |
| Window opacity animation, always-on-top, taskbar identity | **not verified** — needs a Windows compositor |
| Actual Windows memory figures | **not measured** — expect higher than 62 MB once real fonts and DWM surfaces exist |

Everything in that table is a platform limitation of the development sandbox, not a known
defect. It needs one pass on a real Windows 10 machine before Phase 1 is called done.

## Accessibility and low-end machines

* Every control has a tooltip in Hindi; the hotkey chip is a visible reminder.
* Text is selectable, so a transcript can be copied out.
* The window can be resized down to 420×320 for small screens.
* Nothing animates continuously; a machine left in the tray is idle at ~0 % CPU.
