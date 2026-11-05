# Third-Party Notices and Licence Risks

SHRADDHA AI's own code is MIT. Everything below is a separate work with its own
licence. **Read the risk column before shipping commercially.**

## Runtime libraries

| Component | Version pin | Licence | Commercial use | Notes |
|---|---|---|---|---|
| Python (CPython) | 3.11–3.13 | PSF-2.0 | ✅ | permissive |
| PySide6 (Qt for Python) | `>=6.7,<7` | LGPL-3.0 | ✅ | Must ship Qt as **shared** libraries and allow replacement; do not static-link. Qt also offers a commercial licence — LGPL path is fine if obeyed. |
| sounddevice | `>=0.5,<1` | MIT | ✅ | wraps PortAudio (MIT) |
| sherpa-onnx | `>=1.11,<2` | Apache-2.0 | ✅ | runtime only |
| onnxruntime | (dependency of the above) | MIT | ✅ | |
| vosk (optional) | `>=0.3.45` | Apache-2.0 | ✅ | |
| piper-tts (optional) | `>=1.2,<2` | GPL-3.0 | ⚠️ | GPL applies to the engine; linking it into a proprietary app has copyleft implications. Keep Piper in a **separate process** to isolate it, or replace with a permissive engine. |
| pywin32 (optional) | `>=306` | PSF-2.0 | ✅ | Windows only; also backs the Credential Manager key store |
| google-genai (optional, Phase 3) | `>=2.34,<3` | Apache-2.0 | ✅ | official Gemini SDK, imported lazily and only after consent; pulls `httpx`, `pydantic`, `google-auth` (all permissive) |
| SQLite | bundled | Public domain | ✅ | |

## Model weights

| Model | Licence | Commercial use | Notes |
|---|---|---|---|
| Hindi IndicConformer (int8 ONNX) | CC-BY-4.0 | ✅ | attribution required: "IndicConformer, AI4Bharat, CC-BY-4.0" — shown in `--doctor` and shipped in this file |
| Vosk `vosk-model-small-hi-0.22` | Apache-2.0 | ✅ | |
| Whisper / whisper.cpp models | MIT (OpenAI weights) | ✅ | |
| Meta MMS-TTS Hindi | CC-BY-NC-4.0 | ❌ | **non-commercial only** |
| Piper `hi_IN-pratham` / `hi_IN-priyamvada` | trained on CC-BY-NC-SA data | ❌ | **non-commercial only** |
| Piper `hi_IN-rohan` | research-only base model | ❌ | **non-commercial only** |
| Windows OneCore voices (Hemant / Kalpana) | licensed with Windows | ✅ (on licensed Windows) | cannot be redistributed — rely on the OS copy |
| Qwen3 (Phase 6 LLM) | Apache-2.0 | ✅ | cleanest truly-free LLM option |
| Gemma 3 (Phase 6 LLM) | Gemma Terms of Use | ⚠️ | free to use, not OSI-approved, has acceptable-use conditions |

Phase 2 ships **Vosk small-hi** as the default recogniser precisely because it is
Apache-2.0: a 42 MB model, a permissive licence, and no ONNX Runtime to redistribute.
IndicConformer (CC-BY-4.0) is the opt-in upgrade, and the attribution line above is the
one to keep visible if you redistribute a build that includes it.

## Assets and voices: the practical summary

- **Safest default for a product:** Windows OneCore voices for output, IndicConformer/Vosk for input. Everything there is either permissive or licensed with the OS.
- **Best-sounding Hindi output today is non-commercial.** That is a licensing limit, not a technical one. If SHRADDHA AI ever becomes paid, budget for a commercially-licensed voice or fine-tune on audio you own the rights to.

## Not used, and why

| Rejected | Reason |
|---|---|
| Porcupine wake word | free tier requires an access key; paid beyond it → violates "zero paid APIs" |
| openWakeWord (Phase 2) | a second neural runtime for one phrase; the VAD + short-burst ASR path already works with the model that is already loaded |
| PyTorch-based ASR/TTS (MMS, VITS) | ~800 MB of wheel and ~250 MB RSS before a single word — violates the 4 GB target |
| Google / Azure / OpenAI / ElevenLabs **speech** | cloud, paid, and sends your voice off-device. (Gemini *answers* are different: text only, opt-in, free tier — see [docs/AI.md](docs/AI.md)) |
| Electron / Chromium shells | 180–300 MB idle RAM |
| PyTorch | 2 GB+ install for a model that ONNX Runtime runs in 130 MB |

Last reviewed: 2026-11-05.
