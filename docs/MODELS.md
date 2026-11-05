# Model Provisioning

Models are **never committed** to this repository (`.gitignore` blocks `*.onnx`, `*.gguf`,
`*.bin`). They are downloaded on demand into `%LOCALAPPDATA%\Shraddha\models\`
(`SHRADDHA_HOME` overrides the root). Archives are unpacked and removed automatically, and
a member that would escape the models folder is refused.

Use the helper:

```bash
python scripts/fetch_models.py --list
python scripts/fetch_models.py --set asr-light     # ~42 MB  (Vosk small Hindi, Apache-2.0)
python scripts/fetch_models.py --set asr-main      # ~130 MB (IndicConformer Hindi int8, CC-BY-4.0)
python scripts/fetch_models.py --set tts-piper     # ~64 MB  (Piper hi_IN neural voice)
python scripts/fetch_models.py --set all-light     # ~110 MB, 4 GB-RAM friendly
```

## Tiers

| Tier | ASR | TTS | Extra disk | Best for |
|---|---|---|---|---|
| **Minimal** (default) | Vosk `small-hi` (42 MB) | Windows OneCore (0 MB) | 42 MB | 4 GB RAM, old CPUs |
| **Recommended** | IndicConformer int8 (130 MB) | OneCore + optional Piper (64 MB) | ~194 MB | 8 GB, noisy rooms, accents |
| **With LLM** (Phase 6) | any | any | +2.5 GB | free-form Q&A |

Whisper and whisper.cpp were evaluated and rejected in Phase 2: 75 MB–1.5 GB of weights,
2–10× the RAM, no streaming, and no Hindi accuracy gain that justifies it on a 4 GB
machine. The comparison table and the measurements behind it are in
[docs/VOICE.md](VOICE.md#3-which-recognition-engine-and-why).

## Hardware gates

| Requirement | Why |
|---|---|
| x64 CPU with **AVX2** | int8 ONNX kernels + llama.cpp. Almost every CPU since 2013. |
| 4 GB RAM | ASR + TTS + OS comfortably |
| 8 GB RAM | required before enabling the LLM |
| Any microphone | 16 kHz mono is resampled internally; no special hardware needed |

`python -m shraddha --doctor` checks all of the above, plus whether each optional
Python extra is installed and whether Hindi voices are registered with Windows.

## Adding Windows Hindi voices

Windows 10/11 ship Hindi TTS voices (**Hemant** male, **Kalpana** female) but they only
appear after the Hindi speech feature is installed:

1. Settings → Time & Language → Language → **Add a language** → हिन्दी (Hindi).
2. Open the language's options → install **Speech** (Text-to-speech) if not automatic.
3. Settings → Time & Language → **Speech** → set speech language to Hindi.
4. Verify: `powershell -c "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | % { $_.VoiceInfo.Name }"`

Note: Windows 10 **Single Language** editions cannot add languages. On those machines
SHRADDHA AI falls back to the Piper neural voice, which needs no OS language pack.

## Licence reminder

`piper hi_IN` voices are **non-commercial** (trained on CC-BY-NC-SA / research-only
audio). They are the best-sounding free Hindi voices available and are perfect for
personal use — but they cannot ship in a paid product. See `THIRD-PARTY-NOTICES.md`.
