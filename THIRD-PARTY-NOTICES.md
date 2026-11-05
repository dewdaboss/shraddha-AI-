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
| pywin32 (optional) | `>=306` | PSF-2.0 | ✅ | Windows only |
| SQLite | bundled | Public domain | ✅ | |

## Model weights

| Model | Licence | Commercial use | Notes |
|---|---|---|---|
| Hindi IndicConformer (int8 ONNX) | CC-BY-4.0 | ✅ | attribution required |
| Vosk `vosk-model-small-hi-0.22` | Apache-2.0 | ✅ | |
| Whisper / whisper.cpp models | MIT (OpenAI weights) | ✅ | |
| Meta MMS-TTS Hindi | CC-BY-NC-4.0 | ❌ | **non-commercial only** |
| Piper `hi_IN-pratham` / `hi_IN-priyamvada` | trained on CC-BY-NC-SA data | ❌ | **non-commercial only** |
| Piper `hi_IN-rohan` | research-only base model | ❌ | **non-commercial only** |
| Windows OneCore voices (Hemant / Kalpana) | licensed with Windows | ✅ (on licensed Windows) | cannot be redistributed — rely on the OS copy |
| Qwen3 (Phase 6 LLM) | Apache-2.0 | ✅ | cleanest truly-free LLM option |
| Gemma 3 (Phase 6 LLM) | Gemma Terms of Use | ⚠️ | free to use, not OSI-approved, has acceptable-use conditions |

## Assets and voices: the practical summary

- **Safest default for a product:** Windows OneCore voices for output, IndicConformer/Vosk for input. Everything there is either permissive or licensed with the OS.
- **Best-sounding Hindi output today is non-commercial.** That is a licensing limit, not a technical one. If SHRADDHA AI ever becomes paid, budget for a commercially-licensed voice or fine-tune on audio you own the rights to.

## Not used, and why

| Rejected | Reason |
|---|---|
| Porcupine wake word | free tier requires an access key; paid beyond it → violates "zero paid APIs" |
| Google / Azure / OpenAI / ElevenLabs speech | cloud, paid, and sends your voice off-device |
| Electron / Chromium shells | 180–300 MB idle RAM |
| PyTorch | 2 GB+ install for a model that ONNX Runtime runs in 130 MB |

Last reviewed: 2026-11-05.
