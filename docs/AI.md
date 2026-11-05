# Cloud AI (Phase 3) — Google Gemini, opt-in

> **The one-line rule:** SHRADDHA AI is offline by default. Cloud answers exist only after
> *you* supply a key **and** *you* grant consent inside the app. Until then no socket is
> opened, no SDK is imported, and nothing you type or say leaves the machine.

---

## 1. What Phase 3 adds

| Before (Phase 2) | After (Phase 3) |
|---|---|
| Unknown questions get an honest local reply ("मुझे यह नहीं पता…") | They can be answered by Google Gemini, **streamed word by word** into the chat |
| Only the rule engine understands language | The model understands free-form Hindi, Hinglish and English questions |
| Zero network code | One HTTPS request, only when the three-way gate is open |
| — | Configurable model, history window, timeout, token budget, temperature |

What Phase 3 deliberately does **not** change:

* **PC actions are still local.** Opening Chrome, folders and sites, date/time, stop
  listening, voice switching — all still come from `shraddha.commands` and its allowlists.
* **The model cannot act.** `shraddha.ai` has no import of `subprocess`, `ctypes` or
  `shraddha.commands`, and a test (`test_the_ai_package_cannot_act_on_the_computer`)
  keeps it that way. Model output is *text*; it never reaches `ActionExecutor`.
* **Sensitive actions still ask first.** The confirmation gate is untouched.
* **Power actions stay refused.** Unchanged since Phase 2.

---

## 2. The three-way gate

A request reaches Google only when **all** of these are true, checked in this order
(`AiService.status()`):

| # | Condition | Config key | Default |
|---|---|---|---|
| 1 | the master switch is on | `llm.enabled` | `false` |
| 2 | a provider is selected | `llm.provider = "gemini"` | `"none"` |
| 3 | the SDK is installed | `pip install -e '.[ai]'` | absent |
| 4 | an API key is found | env var or Credential Manager | absent |
| 5 | consent was granted **in the app** | `llm.allow_cloud` | `false` |

`status` therefore reports exactly one of:

| Status | Meaning | What the chat shows |
|---|---|---|
| `off` | master switch off (`provider = "none"` on a fresh install) | local answers, no notice |
| `no_provider` | provider not recognised / `local` (Phase 6) | local answers |
| `no_sdk` | `google-genai` missing | local answers + install hint |
| `no_key` | no key found | local answers + `--set-api-key` hint |
| `consent_required` | key present, consent missing | local answer **+ one Hindi consent notice per session** |
| `ready` | everything is in place | streamed Gemini answer |

`--ai-status` prints this state, and `--doctor` adds a `cloud ai (optional)` block with the
same facts (provider, model, masked key source, consent, status).

---

## 3. Consent, in the user's words

Consent is granted by an **exact phrase**, either in the chat window or from the CLI.
Matching is deliberately literal — a *question about* cloud AI must never switch it on.

Grant (any of):

```
क्लाउड AI चालू करो          क्लाउड AI ऑन करो
enable cloud AI             turn on cloud AI
python -m shraddha --ai-consent
```

Revoke (any of):

```
क्लाउड AI बंद करो           क्लाउड AI ऑफ करो
disable cloud AI            turn off cloud AI
python -m shraddha --ai-off
```

Before the first answer, the chat shows this notice (once per session):

> क्लाउड AI अभी बंद है - आपके सवाल आपके कंप्यूटर से बाहर नहीं जाते।
> अगर आप Google Gemini का जवाब चालू करना चाहें, तो लिखिए: "क्लाउड AI चालू करो"
> ध्यान दीजिए: तब आपका सवाल Google को भेजा जाएगा। …

The consent flag is written to `config.json`, so it survives a restart. Revoking it sets
both `enabled` and `allow_cloud` back to `false`.

---

## 4. Setup (three commands)

```bash
pip install -e ".[ai]"                    # 1. the official google-genai SDK (~1.3 MB wheel)

python -m shraddha --set-api-key          # 2. hidden prompt, stores the key in the
                                          #    Windows Credential Manager (target
                                          #    "ShraddhaAI/GeminiApiKey")

python -m shraddha --ai-check             # 3. one real round-trip, prints the answer
python -m shraddha --ai-consent           #    opt in, or use the chat phrase
```

Without `pywin32` (or off Windows) `--set-api-key` explains the environment-variable
alternative instead:

```bat
setx GEMINI_API_KEY "your-key"    :: then open a new terminal
```

### Key precedence (fixed, tested)

1. `llm.api_key_env` if set to something else (configurable escape hatch)
2. `GEMINI_API_KEY`
3. `GOOGLE_API_KEY`
4. Windows Credential Manager → `ShraddhaAI/GeminiApiKey`

Only the **last four characters** are ever printed (`…4f2c`); the key is never written to
`config.json`, the log file, a doctor report or an error message.

---

## 5. Models and the one-level fallback

| Setting | Default | Why |
|---|---|---|
| `llm.model` | `gemini-flash-latest` | Google's rolling flash alias: the model that stays on the free tier |
| `llm.fallback_model` | `gemini-2.5-flash` | an alias can be retired; a 404 is retried **once** with this, before any text is shown |
| `llm.timeout_s` | `30` | per-request HTTP timeout (5–120) |
| `llm.max_output_tokens` | `1024` | keeps answers (and free-tier usage) small (64–8192) |
| `llm.temperature` | `0.6` | natural Hindi without drifting (0–2) |
| `llm.history_turns` | `8` | exchanges sent as context; `0` = stateless (0–50) |
| `llm.stream` | `true` | stream into the chat bubble |

Fallback only fires when the failure is `model_missing` **and** no chunk has been shown —
a retry mid-sentence would duplicate text. A model that answers is remembered for the
session (`provider.active_model`), and `--ai-check` prints which model replied.

Free-tier reality: roughly 15 requests/minute and a few hundred to 1,500 per day per
project. The defaults (short prompt, 1,024 output tokens, 8-turn window) are chosen to
stay inside that, and 429 is handled gracefully rather than retried forever.

---

## 6. Failure handling (what the user actually sees)

Every SDK/transport exception is translated into one Hindi sentence with an actionable
hint — never a traceback, never English stack-trace soup:

| Code | Cause | Retry automatically |
|---|---|---|
| `invalid_key` | key rejected (400/401) | no |
| `forbidden` | key lacks access (403) | no |
| `model_missing` | model/alias retired (404) | once, with the fallback model |
| `rate_limited` | per-minute limit (429) | **once**, after 1 s |
| `quota` | free-tier daily quota spent | no |
| `server_error` | Google 5xx | yes (one retry) |
| `timeout` | request exceeded `llm.timeout_s` | yes (one retry) |
| `network` | offline / DNS / connection reset | yes (one retry) |
| `blocked` | model refused the request | no |
| `empty` | blank answer | no |

Retries happen only **before** the first chunk reaches the chat; after that the answer is
simply cut short and marked with "…". The local rule engine keeps working throughout — an
AI failure degrades to the Phase 2 behaviour, it never disables the assistant.

---

## 7. Threading: why the window never freezes

```
GUI thread ──► AiBridge.ask(text) ──► thread "shraddha-ai"
   ▲                                        │
   │  partial / final / error  (Qt signals) │  AiService.ask() ─► GeminiProvider.stream()
   └────────────────────────────────────────┘         (HTTPS + SDK, always here)
```

* The SDK is imported **on the worker thread**, at the first request — so a user who never
  grants consent never pays the import cost or the memory.
* One request at a time. If a second question arrives while an answer is streaming, the
  controller answers it locally instead of queueing your questions in memory.
* Closing the overlay or quitting cancels the stream (`bridge.cancel()`); the bubble keeps
  what arrived and is marked "…".
* The chat view grows **one** bubble per answer (`begin_stream` → `append_chunk` →
  `finish_stream`), and the reply is spoken once, when it is complete.

---

## 8. Privacy: exactly what is sent, and when

| | Sent to Google | Stays local |
|---|---|---|
| Default install | **nothing** | everything |
| Consent granted, local command ("Chrome खोलो") | **nothing** — the router answers first | the whole command |
| Consent granted, real question | the question + up to `history_turns` previous exchanges + a fixed system prompt | commands, files, folders, clipboard, mic audio, chat history in SQLite |
| `--doctor`, `--ai-status`, `--init` | **nothing** (no socket is opened) | |

Your **voice is never uploaded**: speech is recognised locally by Vosk and only the
recognised *text* of a question can leave the machine — after consent.
Google's free tier may use API content to improve its models; that is stated in the
consent notice, in Hindi, before the first request.

---

## 9. Testing without a key or a network

All 149 AI tests use a **fake client**, so CI never needs `GEMINI_API_KEY`:

| File | Covers |
|---|---|
| `tests/test_ai_gemini.py` | request shape, chunk streaming, model fallback, error translation, lazy SDK import, the "cannot act" invariant |
| `tests/test_ai_service.py` | the three-way gate, exact consent phrases, history window, retry policy, never raising at the UI boundary |
| `tests/test_ai_keys.py` | key precedence, masking, the Credential Manager path (fake `win32cred`) |
| `tests/test_ui_ai.py` | streamed bubbles, worker bridge, controller integration, local-commands-win behaviour |
| `tests/test_cli_ai.py` | `--set-api-key`, `--ai-status`, `--ai-consent`, `--ai-off`, `--ai-check` |
| `tests/test_doctor_ai.py` | the doctor block, masked key, warnings, "the doctor opens no socket" |
| `tests/test_ai_config.py` | schema v3, defaults, ranges, round-trip |

Run them with the rest of the suite:

```bash
pytest                        # 615 tests, no network, no key
pytest tests/test_ai_gemini.py -q
```

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `status no_key` | `python -m shraddha --set-api-key`, or `setx GEMINI_API_KEY "…"` + new terminal |
| `status no_sdk` | `pip install -e ".[ai]"` |
| `status consent_required` | `--ai-consent`, or type "क्लाउड AI चालू करो" |
| `failed [invalid_key]` | key copied wrong or revoked — store a fresh one |
| `failed [rate_limited]` | wait a minute; the free tier allows ~15 requests/minute |
| `failed [quota]` | daily free quota spent — try tomorrow, or use your own billing project |
| `failed [network]` | offline; the assistant keeps answering locally, which is the point |
| Answer looks cut off | the stream timed out or errored mid-answer; ask again |
| Answers in English, not Hindi | Hindi was requested in chat; the model mirrors the question's language — ask in Hindi/Hinglish |

---

## 11. What is verified, and what is not

**Verified in this repository (Linux sandbox, automated):** the gate, consent phrases,
key precedence and masking, request/response shaping against a mocked SDK, model fallback,
retry policy, error translation, streaming into one bubble, worker-thread isolation,
cancellation, CLI commands, doctor block, config schema v3, plus the invariant that the AI
package cannot touch the operating system. 615 tests, `ruff` clean.

**Not verified here — needs one pass on real Windows 10:**

1. `python -m shraddha --set-api-key` against the real Windows Credential Manager
   (`win32cred`), including the `CredManage` entry and a reboot.
2. One live `--ai-check` against Google with a real free-tier key (quota, latency, and
   whether the default alias answers for your project).
3. Streaming smoothness in the real Qt window with Nirmala UI shaping while chunks arrive.
4. Real free-tier limit behaviour under repeated questions (429 handling on a real key).

Nothing in this document claims those were tested on Windows.
