# AwaazAI VoiceAgent

The AI execution service of AwaazAI: conversation orchestration, LLM/STT/TTS integration and streaming. It is deliberately **separate** from `Backend/` (users, auth, agent configuration, database) and `Frontend/`; it shares no code with them.

**Status: Phase 4, step 1 of 7 (text/audio -> Gemini -> speech pipeline over one WebSocket).** `GET /health`, `POST /chat`, `POST /chat/stream` (streamed Gemini replies), `WS /stt/stream` (live transcription) and `POST /tts/stream` (streamed speech) and `WS /voice/stream` (text or raw PCM16 audio in, Gemini's reply out as text and spoken sentences) exist. The browser microphone and frontend integration are **not** built yet: nothing here pretends otherwise.

| Phase | Scope | Status |
|---|---|---|
| 1 | Service skeleton, `/health`, config, errors, request IDs, tests | done |
| 2 | Text agent with Gemini behind a provider interface | done |
| 3A | Streaming Gemini replies over SSE, cancellation, timeouts, TTFT, concurrency limits | **done** |
| 3B | Streaming speech-to-text over WebSocket (Deepgram), limits, cancellation | **done** |
| 3C | Streaming text-to-speech over HTTP (Deepgram Aura or Sarvam Bulbul, switchable; MP3), limits, cancellation | **done** (no real TTS call made yet) |
| 4 | Microphone -> STT -> Gemini streaming -> TTS pipeline, barge-in | **step 1 done**: `WS /voice/stream` (text or raw PCM16 audio over a socket, offline-tested); browser microphone, multi-turn sockets and barge-in not started |
| 5 | Backend / Frontend integration, service-to-service auth | not started |

**Stack:** Python 3.12+ (tested on 3.14.3) · FastAPI · Uvicorn · Pydantic Settings · `google-genai` (Gemini text) · `websockets` + Deepgram (speech-to-text) · `httpx` + Deepgram Aura or Sarvam Bulbul (text-to-speech, `TTS_PROVIDER`). No LiveKit, Docker, Redis, Prisma, LangChain or LangGraph.

## Setup (Windows PowerShell)

```powershell
cd C:\Users\niran\Desktop\AwaazAI\VoiceAgent

python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements-dev.txt

Copy-Item .env.example .env           # skip if you already have a .env: never overwrite it
notepad .env                          # put your key after GEMINI_API_KEY=  (never paste it into chat or commit it)
```

## Run the service (port 8001)

The Backend runs on 8000, so the VoiceAgent uses 8001. Bind to `127.0.0.1` (see [Security](#security-read-this-before-exposing-the-service)) and use **one worker** (sessions live in memory):

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Interactive docs: http://localhost:8001/docs (disabled when `ENVIRONMENT=production`).

WebSocket support comes from the installed `websockets` package. Uvicorn's default WebSocket implementation prints `websockets.legacy` deprecation warnings; add `--ws websockets-sansio` to use its newer implementation (both are covered by the end-to-end tests).

## Run the tests

```powershell
python -m pytest                      # offline: every Gemini call is mocked, no key or internet needed
```

The suite also runs the **real google-genai SDK against a local stand-in for Gemini's streaming endpoint** (`tests/test_sdk_stream_cancellation.py`, localhost only) to prove that cancelling really closes the upstream HTTP connection.

Two optional **real Gemini** smoke tests make real, billable calls (one short chat call, then two short streaming calls). They are skipped unless you opt in, and never print the key, prompts or replies:

```powershell
$env:RUN_GEMINI_SMOKE = "1"; python -m pytest tests/test_gemini_smoke.py tests/test_gemini_stream_smoke.py -v -s; Remove-Item Env:RUN_GEMINI_SMOKE
$env:RUN_STT_SMOKE = "1"; python -m pytest tests/test_stt_smoke.py -v -s; Remove-Item Env:RUN_STT_SMOKE   # needs DEEPGRAM_API_KEY
$env:RUN_TTS_SMOKE = "1"; python -m pytest tests/test_tts_smoke.py -v -s; Remove-Item Env:RUN_TTS_SMOKE   # needs the key of TTS_PROVIDER; saves tts_samples/*.mp3 to listen to
```

## Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | **Secret.** Empty/missing is allowed: the service starts, `/health` works and `/chat`, `/chat/stream` return `503 llm_not_configured`. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | See the **model availability** note below. |
| `LLM_TIMEOUT_SECONDS` | `20` | `/chat`: limit for the whole call. `/chat/stream`: longest wait for the **next chunk**, and longest a slow client may take to accept one event. |
| `LLM_STREAM_TIMEOUT_SECONDS` | `60` | Longest total time for one streamed answer. |
| `LLM_MAX_CONCURRENT_GENERATIONS` | `8` | Simultaneous Gemini calls, shared by `/chat` and `/chat/stream`. |
| `GENERATION_QUEUE_TIMEOUT_SECONDS` | `5` | How long a request waits for a free slot before `503 generation_capacity_reached`. |
| `DEEPGRAM_API_KEY` | *(empty)* | **Secret**, a separate credential from Gemini. Empty is allowed: `/stt/stream` then reports `stt_not_configured`. |
| `DEEPGRAM_MODEL`, `DEEPGRAM_URL` | `nova-3`, `wss://api.deepgram.com/v1/listen` | The URL must be `wss://` (`ws://` only for localhost test servers). |
| `DEEPGRAM_LANGUAGE_ENGLISH` / `_HINDI` / `_HINGLISH` | `en` / `hi` / `multi` | Our language name -> Deepgram language code. See [Languages](#languages). |
| `DEEPGRAM_ENDPOINTING_MS`, `DEEPGRAM_ENDPOINTING_MS_HINGLISH` | `300`, `100` | Silence (ms) that marks the end of an utterance; the second applies to `hinglish` (`multi`) only, as Deepgram recommends 100 for code-switching. |
| `STT_IDLE_TIMEOUT_SECONDS`, `STT_FINISH_TIMEOUT_SECONDS`, `STT_CONNECT_TIMEOUT_SECONDS`, `STT_SEND_TIMEOUT_SECONDS` | `8`, `10`, `10`, `10` | See [Limits, timeouts and cancellation](#limits-timeouts-and-cancellation). Idle must stay below 10 (Deepgram's own limit). |
| `STT_MAX_STREAM_SECONDS`, `STT_MAX_AUDIO_SECONDS`, `STT_MAX_CHUNK_BYTES`, `STT_MAX_CONCURRENT_STREAMS` | `300`, `120`, `32768`, `4` | Per-stream and global limits. |
| `STT_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Browser origins allowed to open the WebSocket (comma-separated; `*` is rejected in production). |
| `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS` | `0.7`, `512` | Keep spoken replies short. |
| `SESSION_MAX_SESSIONS`, `SESSION_TTL_SECONDS`, `SESSION_MAX_TURNS`, `SESSION_MAX_HISTORY_CHARS`, `SESSION_LOCK_TIMEOUT_SECONDS` | `1000`, `1800`, `20`, `12000`, `30` | See [Conversation sessions](#conversation-sessions). |
| `TTS_PROVIDER` | `deepgram` | `deepgram` or `sarvam`. See [Text-to-speech](#text-to-speech-post-ttsstream-phase-3c). |
| `SARVAM_API_KEY` | *(empty)* | **Secret.** Needed when `TTS_PROVIDER=sarvam`; empty gives `503 tts_not_configured`. |
| `SARVAM_TTS_MODEL`, `SARVAM_LANGUAGE_ENGLISH/_HINDI/_HINGLISH`, `SARVAM_SPEAKER_ENGLISH/_HINDI/_HINGLISH`, `SARVAM_TTS_VOICES`, `SARVAM_TTS_SAMPLE_RATE`, `SARVAM_TTS_BITRATE`, `SARVAM_TTS_URL` | see `.env.example` | Sarvam model, language codes, speakers and audio format. |
| `DEEPGRAM_TTS_MODEL`, `DEEPGRAM_TTS_VOICES`, `DEEPGRAM_TTS_BIT_RATE`, `DEEPGRAM_TTS_URL` | `aura-2-thalia-en`, *(empty)*, `48000`, `https://api.deepgram.com/v1/speak` | TTS voice and format (same `DEEPGRAM_API_KEY` as STT). See [Text-to-speech](#text-to-speech-post-ttsstream-phase-3c). |
| `TTS_TIMEOUT_SECONDS`, `TTS_STREAM_TIMEOUT_SECONDS`, `TTS_SEND_TIMEOUT_SECONDS`, `TTS_MAX_TEXT_CHARS`, `TTS_MAX_CONCURRENT_REQUESTS`, `TTS_QUEUE_TIMEOUT_SECONDS` | `15`, `60`, `10`, `2000`, `4`, `2` | TTS limits. |
| `VOICE_MAX_CONCURRENT_TURNS`, `VOICE_TURN_TIMEOUT_SECONDS`, `VOICE_SENTENCE_QUEUE_SIZE`, `VOICE_MAX_SENTENCE_CHARS` | `4`, `90`, `3`, `300` | Whole-pipeline limits for [`WS /voice/stream`](#voice-turns-ws-voicestream-phase-4-step-1). |
| `ENVIRONMENT`, `LOG_LEVEL`, `SERVICE_NAME` | see `.env.example` | Invalid values stop the service at startup. |

`.env` is git-ignored. The key is read only from the environment, held as a masked secret, and is never logged or returned.

> **Model availability (important).** Google retires and re-provisions models quickly, and the model list can show models you cannot call. During development: `gemini-2.5-flash` and `gemini-2.5-flash-lite` returned *"no longer available to new users"* (`502 llm_model_unavailable`); `gemini-3.8-flash` and `gemini-flash-latest` were erratic, with the raw SDK (no AwaazAI code) hitting a 60 s read timeout in 3 of 4 attempts and a 10 s first chunk when it did answer; `gemini-3.5-flash` was responsive (first chunk ~1.5 s) and passed the real smoke tests. These are point-in-time observations on one account, not guarantees. Set `GEMINI_MODEL` in `.env` to a model that works for you and test it with the smoke test before relying on it. Prefer a pinned name over `*-latest` aliases, which change behaviour silently.

## `POST /chat` (complete reply)

Request / response, validation and errors are unchanged from Phase 2.

```json
{ "message": "Namaste! Introduce yourself.", "session_id": "demo-session-001", "language": "hinglish" }
```
```json
{ "session_id": "demo-session-001", "reply": "Namaste! Main AwaazAI hoon ...", "model": "<configured model>" }
```

| Field | Rules |
|---|---|
| `message` | Required, 1-2000 characters, must contain non-whitespace text (trimmed). |
| `session_id` | Optional, `A-Z a-z 0-9 _ -`, 1-64 characters. A random 32-character ID is generated and returned when omitted. |
| `language` | `english`, `hindi` or `hinglish` (default `hinglish`). Can change between turns. |
| anything else | Rejected with 422 (for example a client-supplied `user_id`). |

## `POST /chat/stream` (streamed reply, Server-Sent Events)

Same request body, validation, languages, session history and system instruction as `/chat`, but the reply is sent **as Gemini produces it** instead of after the whole answer exists.

```json
{ "message": "Explain AI agents in simple Hinglish.", "session_id": "stream-demo-001", "language": "hinglish" }
```

Response `200`, `Content-Type: text/event-stream; charset=utf-8`, `X-Accel-Buffering: no` (so nginx-style proxies do not buffer it). Each event is `event: <name>` + one line `data: <json>` + a blank line:

```
event: start
data: {"session_id":"stream-demo-001","model":"gemini-3.5-flash","request_id":"1f0c9a7e5d2b4a68"}

event: token
data: {"text":"AI agents "}

event: token
data: {"text":"ek aisa software hota hai "}

event: done
data: {"session_id":"stream-demo-001","model":"gemini-3.5-flash","ttft_ms":1771.2,"total_ms":2434.2,"chunks":5}
```

| Event | When | Payload |
|---|---|---|
| `start` | Once, as soon as the **first** text chunk exists | `session_id`, `model`, `request_id` |
| `token` | One per chunk Gemini produced, immediately | `text` (concatenate all `text` values to get the reply; chunks may start/end mid-word) |
| `done` | Once, after the complete answer | `session_id`, `model`, `ttft_ms`, `total_ms`, `chunks` |
| `error` | Instead of `done`, if generation fails after the stream started | `code`, `message`, `request_id` (same codes as the table below) |

A stream ends with exactly one of `done` or `error`. If neither arrives (connection dropped) the answer is incomplete and was not stored.

### Try it locally

Start the service, then use PowerShell. `curl.exe` is the real curl (plain `curl` is an alias for something else in Windows PowerShell) and `-N` turns off its buffering:

```powershell
'{"message":"Explain AI agents in simple Hinglish.","session_id":"stream-demo-001","language":"hinglish"}' |
  curl.exe -N -X POST http://127.0.0.1:8001/chat/stream -H "Content-Type: application/json" --data-binary "@-"
```

You should see the events appear one after another over a second or two, not all at once. Or with Python, which also prints arrival times (`httpx` is already installed in the venv):

```powershell
@'
import httpx, time
t0 = time.monotonic()
body = {"message": "Explain AI agents in simple Hinglish.", "session_id": "stream-demo-001", "language": "hinglish"}
with httpx.stream("POST", "http://127.0.0.1:8001/chat/stream", json=body, timeout=60) as r:
    for line in r.iter_lines():
        if line.startswith("event:") or line.startswith("data:"):
            print(f"{time.monotonic() - t0:5.2f}s  {line}")
'@ | python -
```

### How streaming differs from `/chat`

| | `POST /chat` | `POST /chat/stream` |
|---|---|---|
| Reply | One JSON body after the whole answer exists | SSE events as Gemini produces them |
| Time to first text | The full generation time (3-6 s typical) | **TTFT** (first chunk, ~1-2 s typical) |
| Failure before any text | HTTP error JSON | **The same** HTTP error JSON and status codes |
| Failure after text started | n/a (all or nothing) | An SSE `error` event, then the stream ends |
| Client disconnect | Generation finishes anyway | **Generation is cancelled** |
| History | Stored after success | Stored after success (only the complete reply, never a partial one) |

### Errors

Every error before the stream starts has the standard shape `{"error": {"code", "message", "details"?, "request_id"}}` with a real HTTP status. After the stream has started, the status is already `200`, so the same codes arrive as an `error` event. A failed call is **never** answered with a made-up reply, and nothing from a failed or cancelled stream is added to the history.

| HTTP | `code` | Meaning |
|---|---|---|
| 422 | `validation_error` | Invalid body (field names and messages only: submitted text is never echoed). |
| 503 | `llm_not_configured` | `GEMINI_API_KEY` is missing. |
| 502 | `llm_authentication_failed` | Gemini rejected the key. |
| 502 | `llm_model_unavailable` | The model name is unknown or retired for this account (`GEMINI_MODEL`). |
| 429 | `llm_rate_limited` | Gemini quota or rate limit reached. |
| 504 | `llm_timeout` | Gemini produced nothing for `LLM_TIMEOUT_SECONDS`, or the answer exceeded `LLM_STREAM_TIMEOUT_SECONDS`. |
| 503 | `llm_unavailable` | Network failure or Gemini 5xx. |
| 502 | `llm_bad_response` | Empty or unusable reply (e.g. blocked by Gemini's safety filters, or only whitespace). |
| 502 | `llm_provider_error` | Any other provider failure. |
| 409 | `session_busy` | Another request for this session did not finish within `SESSION_LOCK_TIMEOUT_SECONDS`. |
| 503 | `session_capacity_reached` | Every session slot is busy mid-request. |
| 503 | `generation_capacity_reached` | `LLM_MAX_CONCURRENT_GENERATIONS` generations are running and none freed up within `GENERATION_QUEUE_TIMEOUT_SECONDS`. |
| 500 | `internal_error` | Unexpected error (details only in the server log, never the message text). |

All responses, including streams and errors, carry `X-Request-ID` and the security headers. `GET /health` never calls Gemini.

### Cancellation and timeouts

- **Client disconnect:** the server notices (also while waiting for the first chunk), stops the generation, closes the upstream Gemini request, and releases the session lock and generation slot. The unfinished answer is discarded.
- **Gemini hangs:** if no chunk arrives for `LLM_TIMEOUT_SECONDS`, or the whole answer takes longer than `LLM_STREAM_TIMEOUT_SECONDS`, the stream ends with `llm_timeout` (HTTP 504 if nothing was sent yet, otherwise an `error` event) and everything is released.
- **Slow or stalled client:** if a client does not accept an event within `LLM_TIMEOUT_SECONDS`, it is dropped and its generation cancelled, so one stuck reader cannot hold a session or a Gemini slot.
- **Ordering:** cleanup always closes the upstream stream first, then frees the lock and slot.
- **Same session:** requests for one `session_id` are processed one at a time (a second waits up to `SESSION_LOCK_TIMEOUT_SECONDS`, then `409`). Different sessions run in parallel up to `LLM_MAX_CONCURRENT_GENERATIONS`.

**What was actually verified (and its limits).** With the real `google-genai` SDK against a local stand-in for Gemini's streaming endpoint, disconnecting the client, an idle timeout, and abandoning the stream each close the upstream connection and stop the (simulated) generation (`tests/test_sdk_stream_cancellation.py`), and the same chain was exercised through a real uvicorn server. What Google's servers do with an abandoned generation is not observable from a client and is **not** claimed.

*SDK finding that shaped the design:* closing the SDK's stream with `aclose()` does **not** close the HTTP connection (its generators are nested and the connection is only released when a network read is cancelled; even `gc.collect()` did not help). So `GeminiProvider.stream()` runs the SDK iteration in its own task and cancels that task to stop; chunks are handed over through an in-memory queue (capped at 2048 chunks, far above one reply). Consequence: the SDK may read a few chunks ahead of a slow consumer, bounded by `LLM_MAX_OUTPUT_TOKENS`.

### Measuring TTFT (time to first token)

`done.ttft_ms` is the time from when the request reached the service to the first text chunk (it includes any wait for the session lock or a free slot). `done.total_ms` is the time to the end of generation. Both use a monotonic clock. Every stream also logs one privacy-safe line, for example:

```
stream finished: outcome=completed error=- model=gemini-3.5-flash queue_ms=0 ttft_ms=1771 total_ms=2434 chunks=5
```

`outcome` is `completed`, `failed`, `timeout` or `cancelled`. It never contains prompts, replies, session IDs or the key. The access log line (`POST /chat/stream -> 200`) is written when the response *starts*, so its duration is roughly the TTFT, not the stream length.

## Speech-to-text: `WS /stt/stream` (Phase 3B)

Live transcription of microphone audio. It is a **WebSocket** (audio flows client -> server while transcript events flow server -> client), separate from the text-chat endpoints, and it is **not connected to Gemini** yet: it only transcribes. Text chat (`/chat`, `/chat/stream`) is unchanged.

### Provider choice and trade-offs

| Option | Verdict |
|---|---|
| **Deepgram Nova-3 live streaming** | **Chosen.** Documented WebSocket API with interim and final results, `hi` (Hindi), `en`/`en-IN` (English) and a multilingual code-switching mode (`multi`, which lists Hindi and English), a simple API-key auth, an official Python SDK, and free signup credit. |
| Gemini Live "input transcription" | Rejected as the STT. It is a feature of a conversational preview API (the model also generates replies), with forum reports of transcription stalling mid-stream, and no documented language or latency guarantees. Using it as a transcriber would be a hack. |
| Google Cloud Speech-to-Text v2 (gRPC) | Not chosen: heavier setup (Google Cloud project, service-account credentials, billing) for no clear gain in this phase. |

How it talks to Deepgram: directly over its documented WebSocket protocol with the `websockets` library (already installed; pinned in `requirements.txt`), **not** the Deepgram SDK. The protocol is small and published as an AsyncAPI spec; owning the connection gives deterministic teardown on cancellation (a lesson from the Gemini SDK, see above) and adds no dependency. The STT provider is kept strictly separate from the Gemini text provider (`app/stt/` vs `app/llm/`), behind a provider-independent interface, so another STT can be added later.

Trade-offs you accept: a **new credential and account**, a third party processes your audio, and Deepgram closes a connection that receives no audio for ~10 s.

**Hinglish, honestly** (re-verified against Deepgram's docs in Phase 3D, see [Languages](#languages)). Deepgram documents *no Hinglish mode* and no Roman-script Hindi mode for Nova-3. For `language: "hinglish"` we use Nova-3's `multi` mode, which Deepgram documents as real-time code-switching among English, Spanish, French, German, **Hindi**, Russian, Portuguese, Japanese, Italian and Dutch. So Hindi + English code-switching is a supported combination. What is **not** documented, and not verified by us on real speech: in which script Hindi words come back (Devanagari or Roman), and how accurate code-switched speech is. **Nothing here promises Hinglish accuracy.** STT transcribes what was said; it does **not** translate or transliterate.

### Setup

Create a key at https://console.deepgram.com, then add it to your existing `VoiceAgent/.env` yourself (never paste it into chat or commit it):

```
DEEPGRAM_API_KEY=your-key-here
```

Restart the service. Without the key the service still starts, `/health` and the chat endpoints work, and `/stt/stream` accepts the connection and sends `error` with code `stt_not_configured`.

### Audio format (what the endpoint accepts)

| | Requirement | Why |
|---|---|---|
| Encoding | `linear16`: raw PCM, signed 16-bit little-endian, **no WAV header** | Deepgram's raw formats need an explicit `sample_rate`; this is the simplest unambiguous format |
| Channels | `1` (mono) | Multichannel returns per-channel results, which this phase does not model |
| Sample rate | one of `8000, 16000, 22050, 24000, 44100, 48000` (16000 recommended) | A browser must resample its microphone to one of these |
| Frame | binary WebSocket message holding a **whole number of samples** (even number of bytes), at most `STT_MAX_CHUNK_BYTES` (32768 = 1 s at 16 kHz); 20-250 ms frames are ideal | Deepgram's guidance, and bounded memory |
| Pacing | real time; sustained sending faster than 2x real time (after a 10 s burst allowance) is rejected | This is for live speech, not bulk uploads |
| Continuity | keep sending frames (silence is fine); no message for `STT_IDLE_TIMEOUT_SECONDS` (8 s) ends the stream | Deepgram closes after ~10 s without audio |

### Protocol

**Client -> server**

1. First, one **text** frame (JSON): `{"type":"config","sample_rate":16000,"channels":1,"language":"hinglish"}`. `encoding` is optional (`"linear16"`); `channels` defaults to `1`; `language` is `english`, `hindi` or `hinglish` (default `hinglish`). Types are strict (`"16000"` as a string is rejected) and unknown fields are rejected.
2. Then **binary** frames of audio.
3. Finally one **text** frame: `{"type":"end"}`. (Closing the connection instead cancels the stream.)

**Server -> client** (always JSON text frames with a `type`):

```json
{"type":"ready","stream_id":"…32 hex…","request_id":"…16 hex…","language":"hinglish","model":"nova-3","sample_rate":16000,"channels":1}
{"type":"partial","seq":1,"text":"namaste"}
{"type":"partial","seq":2,"text":"namaste duniya"}
{"type":"final","seq":3,"text":"namaste duniya","start":0.0,"duration":1.2,"speech_final":true,"confidence":0.97}
{"type":"done","stream_id":"…","audio_seconds":3.7,"partials":12,"finals":2,"first_partial_ms":640.2,"first_final_ms":1710.8,"total_ms":4120.5}
{"type":"error","code":"stt_idle_timeout","message":"No audio was received for too long.","request_id":"…"}
```

| Event | Meaning |
|---|---|
| `ready` | The stream is open (config accepted, provider connected). Send audio after this. `stream_id` identifies this STT stream only: it is never a text-chat `session_id`. |
| `partial` | An interim hypothesis for the speech still being spoken. It **may change** and is superseded by later partials and finally a `final`. Only sent when the text **changed**: the same partial is never repeated. |
| `final` | Stable text for one audio segment; finals never repeat earlier text, so concatenating them in `seq` order gives the transcript. `speech_final: true` means the speaker paused (a good moment to treat the utterance as complete). `start`/`duration` are seconds; `confidence` may be `null`. |
| `done` | Sent once after `end`, when all final transcripts were flushed. The connection then closes (code 1000). |
| `error` | A safe `code` and `message` (optionally `details` listing field names for a bad config; submitted values are never echoed). The connection then closes. |

`seq` increases across partials and finals. A stream ends with exactly one `done` or `error`.

### Try it locally

With the service running (and `DEEPGRAM_API_KEY` set), this streams a mono 16-bit WAV file at real-time speed (PowerShell):

```powershell
@'
import asyncio, json, wave, websockets

async def main(path):
    wav = wave.open(path)                     # must be mono 16-bit PCM
    assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
    rate = wav.getframerate()
    async with websockets.connect("ws://127.0.0.1:8001/stt/stream") as ws:
        await ws.send(json.dumps({"type": "config", "sample_rate": rate, "language": "english"}))

        async def listen():
            async for message in ws:
                event = json.loads(message)
                print(event["type"], event.get("text", event.get("code", "")))
        listener = asyncio.create_task(listen())

        step = int(rate * 0.02)               # 20 ms frames, paced like a live microphone
        while frames := wav.readframes(step):
            await ws.send(frames)
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "end"}))
        await listener

asyncio.run(main(r"C:\path\to\speech.wav"))
'@ | python -
```

No recording handy? The opt-in smoke test synthesizes a sentence with Windows' built-in speech and streams it:

```powershell
$env:RUN_STT_SMOKE = "1"; python -m pytest tests/test_stt_smoke.py -v -s; Remove-Item Env:RUN_STT_SMOKE
# Hindi / Hinglish on YOUR recordings: see "Evaluating Hindi and Hinglish STT on real speech" below
```

A browser client (Phase 7) must capture the microphone (`AudioWorklet`), resample to 16 kHz mono, convert Float32 to Int16 little-endian, and send ~20-100 ms binary frames.

### Languages

Selected per stream by the `language` field of the config message (default `hinglish`, so Phase 3B clients are unaffected). All three use `model=nova-3`.

| `language` | Deepgram `language` (default, configurable) | `endpointing` | What Deepgram documents |
|---|---|---|---|
| `english` | `en` (`DEEPGRAM_LANGUAGE_ENGLISH`; Nova-3 also lists `en-IN`, `en-US`, `en-GB`, `en-AU`, `en-NZ`) | `DEEPGRAM_ENDPOINTING_MS` (300) | Supported. Use `en-IN` for Indian-accented English. |
| `hindi` | `hi` (`DEEPGRAM_LANGUAGE_HINDI`) | `DEEPGRAM_ENDPOINTING_MS` (300) | Supported (the only Hindi code for Nova-3). Devanagari output is expected, not documented. |
| `hinglish` | `multi` (`DEEPGRAM_LANGUAGE_HINGLISH`) | `DEEPGRAM_ENDPOINTING_MS_HINGLISH` (**100**) | `multi` code-switching covers Hindi and English among 10 languages. Deepgram's code-switching guide **recommends `endpointing=100`**, so Hinglish uses it (Phase 3D change; set it to 300 to restore the old behaviour). |

What was checked in the docs, and what that means:

- **Does `multi` support the Hindi-English combination?** Yes, Hindi and English are both in Nova-3's `multi` list, and the streaming WebSocket accepts `language=multi`. The existing mapping was correct and is kept.
- **`hi-Latn`** (Roman-script Hindi) is listed only for Deepgram's legacy Nova/Base models, **not** Nova-3. We do not send it and `language: "hi-Latn"` is rejected by the config message.
- **Scripts.** Devanagari Hindi and Roman Hinglish both reach the client exactly as Deepgram returns them (byte-identical, no normalisation, translation or transliteration; covered by offline tests). Which script Deepgram *chooses* is not documented for Nova-3 and has to be measured.
- **Alternative not adopted:** Deepgram's Flux multilingual model (`flux-general-multi`) also lists Hindi and adds per-turn language info, but it uses the separate `/v2/listen` protocol with different events. Adopting it would change this service's STT contract, so it is a possible later phase, not part of this one.
- **Not exposed:** per-word language tags that `multi` returns (`words[].language`) are ignored; the `/stt/stream` event shapes are unchanged.

### Evaluating Hindi and Hinglish STT on real speech

The normal suite cannot tell you how well real Deepgram recognises real speech. Record short WAVs yourself (mono, 16-bit PCM; Windows speech synthesis has no Hindi voice) and run the opt-in cases. Suggested natural phrases:

| Case | Phrase to say | Env var |
|---|---|---|
| English | "Hello, I would like to book an appointment for tomorrow." | `STT_SMOKE_AUDIO` (a synthesized English sentence is used if unset) |
| Hindi | "नमस्ते, मैं कल अपॉइंटमेंट बुक करना चाहता हूँ।" | `STT_SMOKE_HINDI_AUDIO` |
| Romanised Hinglish (say it the way you would speak it) | "Main kal appointment book karna chahta hoon, please confirm kar dena." | `STT_SMOKE_HINGLISH_AUDIO` |
| Devanagari Hindi with English words | "मुझे कल का appointment confirm करना है।" | `STT_SMOKE_MIXED_AUDIO` |

```powershell
$env:RUN_STT_SMOKE = "1"
$env:STT_SMOKE_HINDI_AUDIO = "C:\audio\hindi.wav"; $env:STT_SMOKE_HINGLISH_AUDIO = "C:\audio\hinglish.wav"; $env:STT_SMOKE_MIXED_AUDIO = "C:\audio\mixed.wav"
python -m pytest tests/test_stt_smoke.py -v -s
```

Each case that has a WAV runs once or twice (the same Hindi audio in `hindi` and `hinglish` mode; the same Hinglish audio in `hinglish` and `hindi` mode, so you can compare `multi` against `hi`) and prints only the mode, audio length, number of final segments, the **count of Devanagari and of Latin letters** in the transcript, and time to first final. It never prints the transcript, so to judge accuracy and script, also run the same WAV through the manual client above and read the output yourself. Cases without a WAV are skipped. These are billable calls: nothing runs unless `RUN_STT_SMOKE=1`.

### Limits, timeouts and cancellation

| Limit | Setting (default) | When exceeded |
|---|---|---|
| Chunk size | `STT_MAX_CHUNK_BYTES` (32768) | `stt_limit_exceeded`, close 1009 |
| Total audio per stream | `STT_MAX_AUDIO_SECONDS` (120) | `stt_limit_exceeded`, close 1009 |
| Faster-than-real-time audio | 2x real time + 10 s burst | `stt_limit_exceeded`, close 1009 |
| Idle (no client message) | `STT_IDLE_TIMEOUT_SECONDS` (8) | `stt_idle_timeout`, close 1008 |
| Total stream duration | `STT_MAX_STREAM_SECONDS` (300) | `stt_stream_timeout`, close 1008 |
| Waiting for finals after `end` | `STT_FINISH_TIMEOUT_SECONDS` (10) | `stt_timeout`, close 1011 |
| Connecting to Deepgram | `STT_CONNECT_TIMEOUT_SECONDS` (10) | `stt_timeout`, close 1011 |
| Client too slow to accept an event | `STT_SEND_TIMEOUT_SECONDS` (10) | stream dropped |
| Simultaneous streams | `STT_MAX_CONCURRENT_STREAMS` (4) | `stt_capacity_reached`, close 1013 (retry later) |

- **Client disconnect:** the server notices, cancels both directions, **closes the upstream Deepgram connection** and frees the slot. A cancelled stream is not "finalized".
- **Any failure or timeout:** both child tasks are cancelled and awaited, the provider connection is closed, then the stream slot is released, in that order, on every path.
- **No buffering of recordings:** a client frame is read only after the previous one was handed to Deepgram (backpressure), so memory use does not grow with audio length. Nothing is written to disk or a database.

### Errors

| `code` | Close code | Meaning |
|---|---|---|
| `stt_not_configured` | 1011 | `DEEPGRAM_API_KEY` is missing. |
| `stt_invalid_config` | 1008 | Bad or missing config message, unsupported control message, audio sent before config. |
| `stt_invalid_audio` | 1008 | Empty frame, odd byte count, or Deepgram could not decode the audio. |
| `stt_limit_exceeded` | 1009 | Chunk, duration or speed limit (see above). |
| `stt_idle_timeout`, `stt_stream_timeout` | 1008 | Idle or total-duration limit. |
| `stt_authentication_failed` | 1011 | Deepgram rejected the key. |
| `stt_rate_limited` | 1011 | Deepgram quota or concurrency limit reached. |
| `stt_unavailable` | 1011 | Deepgram unreachable or 5xx. |
| `stt_timeout` | 1011 | Deepgram did not connect or finish in time. |
| `stt_provider_error`, `stt_bad_response` | 1011 | Other provider failure, or a malformed message from Deepgram. |
| `stt_capacity_reached` | 1013 | Too many streams are active. |
| `internal_error` | 1011 | Unexpected error (details only in the server log, never the message text). |

A browser whose `Origin` is not in `STT_ALLOWED_ORIGINS` is refused during the HTTP handshake (403) before any WebSocket exists. Clients that send no `Origin` header (scripts, curl, the Backend) are not affected. The handshake response carries `X-Request-ID` and basic security headers, and `ready` / `error` events repeat the request ID.

### Security and privacy

- **The endpoint has no authentication yet** and spends your Deepgram credit (same status as `/chat`). Keep it on `127.0.0.1`. The allowed-origins list protects against a malicious *web page* using your browser to reach it; it is **not** authentication.
- The API key is sent only in the `Authorization` header of a `wss://` connection (`ws://` is accepted only for localhost test servers) and is never logged, returned or stored.
- Never logged: audio, transcripts, the key, stream or request IDs next to content, provider error text. One metadata line per stream (outcome, language, byte and event counts, timings).
- **Verified leak fixed:** the `websockets` library itself logs every frame (including the `Authorization` header and transcript JSON) at DEBUG level. The logging setup pins `websockets`, `httpx` and `httpcore` to WARNING, so even `LOG_LEVEL=DEBUG` cannot expose them (covered by tests).
- Audio and transcripts exist only in memory for the life of the stream. A stream's state is lost on restart and is not shared between workers.

### What was tested, and what was not

- **Offline, mocked provider events** (the normal suite): events and ordering, partial de-duplication, languages, audio validation and limits, timeouts, disconnects, stalled clients, cleanup order, concurrency limits, origin checks, headers and request IDs, error mapping, and logs.
- **Offline, over real sockets:** the real Deepgram client talks to a local server that implements the documented protocol (handshake query and `Authorization` header, `Results` messages, `Finalize`/`CloseStream`, close codes), driven end to end through a real uvicorn server by a real WebSocket client, including proof that a client disconnect closes the upstream connection.
- **Offline language tests (Phase 3D):** per-language Deepgram parameters (model, `language`, `endpointing`) against the local fake server, configuration overrides, byte-identical Devanagari, Roman and mixed-script transcripts through the provider and the WebSocket protocol, and backward compatibility for clients that send no `language`.
- **NOT tested: real Deepgram, real speech recognition, real Hinglish.** No real Deepgram STT call has been made by us. The opt-in smoke tests (above) are ready for you to run. Also unverified against the live service: Deepgram's exact error/close behaviour beyond what its docs state, and whether `KeepAlive` helps (the docs conflict, so it is not used).

## Text-to-speech: `POST /tts/stream` (Phase 3C)

Speaks text through one of two interchangeable providers, chosen by `TTS_PROVIDER` (default `deepgram`). Audio is relayed to the caller chunk by chunk as the provider produces it: nothing is buffered, and the text is synthesized **exactly as sent** (never translated, transliterated or rewritten). TTS is **not** connected to STT or Gemini yet (that is Phase 4).

| `TTS_PROVIDER` | Endpoint (official docs) | Key | Hindi / Hinglish |
|---|---|---|---|
| `deepgram` (default) | `POST https://api.deepgram.com/v1/speak`, model `aura-2-thalia-en` | `DEEPGRAM_API_KEY` (shared with STT) | **No.** Aura has no Hindi model and no Indian accent: English only in practice. |
| `sarvam` | `POST https://api.sarvam.ai/text-to-speech/stream`, model `bulbul:v4-flash` | `SARVAM_API_KEY` | Documented support for Hindi, English (`en-IN`) and English-Hindi code-mixed (`enhi`) voices. **Not yet listened to by us**: see the listening plan. |

### Switch providers

```powershell
# in VoiceAgent/.env (never commit it), then restart the service
TTS_PROVIDER=sarvam
SARVAM_API_KEY=<your key>
```

Back to Deepgram: `TTS_PROVIDER=deepgram`. Both providers stay usable, share the same endpoint, response contract, limits and error codes, and run behind the interface in `app/tts/base.py`. If the selected provider's key is missing the service still starts and `/tts/stream` answers `503 tts_not_configured` (a key for the *other* provider does not count).

### Request and response

```powershell
# Save to a file (curl.exe, not the PowerShell alias), then play it
'{"text":"Namaste! Main aapki appointment book karne mein help kar sakta hoon.","language":"hinglish"}' | Set-Content -Encoding utf8 body.json
curl.exe -N -X POST http://127.0.0.1:8001/tts/stream -H "Content-Type: application/json" --data-binary "@body.json" -o reply.mp3
start reply.mp3
```

In a browser: `const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body}); const blob = await r.blob(); new Audio(URL.createObjectURL(blob)).play();` (progressive playback with `MediaSource` is a frontend concern for a later phase).

| Request field | Notes |
|---|---|
| `text` | Required, trimmed, non-blank, at most `TTS_MAX_TEXT_CHARS` (default and maximum 2000, below both providers' own limits). |
| `language` | `english`, `hindi` or `hinglish` (default `hinglish`). With Sarvam it selects the `language_code` **and** the default speaker; with Deepgram it changes nothing. |
| `voice` | Optional. Omitted or `"default"` selects the provider's default for `language`; otherwise it must be on that provider's allowlist (below). Anything else is `422 tts_invalid_voice`. Unknown fields are rejected. |

**Response:** `200`, `Content-Type: audio/mpeg`, chunked transfer, MP3 (Deepgram: fixed 22050 Hz at `DEEPGRAM_TTS_BIT_RATE`; Sarvam: `SARVAM_TTS_SAMPLE_RATE`/`SARVAM_TTS_BITRATE`, 24000 Hz / 128k default). Headers also include `Cache-Control: no-store, no-transform`, `X-Accel-Buffering: no` (stops nginx-style proxies buffering), `X-Request-ID` and the usual security headers.

### Sarvam parameters (from docs.sarvam.ai; nothing invented)

| Our setting | Sent to Sarvam as | Default / values |
|---|---|---|
| `SARVAM_API_KEY` | header `api-subscription-key` | secret, never logged |
| `SARVAM_TTS_MODEL` | `model` | `bulbul:v4-flash` (Sarvam's recommended for new integrations); also `bulbul:v3`, `bulbul:v2` |
| `language` -> `SARVAM_LANGUAGE_ENGLISH / _HINDI / _HINGLISH` | `language_code` | `en-IN` / `hi-IN` / `hi-IN` (see below) |
| default speaker -> `SARVAM_SPEAKER_ENGLISH / _HINDI / _HINGLISH` | `speaker` | `dev_en_conversational` / `kavya_hi_conversational` / `simran_enhi_customer` |
| `SARVAM_TTS_VOICES` | allowlist of extra speakers a client may request | empty |
| (fixed) | `output_audio_codec` | `mp3` |
| `SARVAM_TTS_SAMPLE_RATE`, `SARVAM_TTS_BITRATE` | `speech_sample_rate`, `output_audio_bitrate` | `24000` (8000/16000/22050/24000 when streaming), `128k` |
| `text` | `text` | unchanged |

Things Sarvam's docs say, and what we do about them:

- **Speakers belong to one model.** The defaults above are `bulbul:v4-flash` ids (`<name>_<lang>_<style>`: `hi` Hindi, `en` English, `enhi` English-Hindi code-mixed). If you switch to `bulbul:v3`, also set the three `SARVAM_SPEAKER_*` to v3 names such as `shubh`. Speaker ids are validated (lowercase, case-sensitive pattern) and only the configured ones are accepted from clients; nothing is passed through.
- **Romanised Hindi lowers quality.** Sarvam states that romanised Indic input "significantly reduces output quality" and recommends native script (Devanagari) for Indic words. We deliberately do **not** transliterate: for Hinglish, feed Devanagari Hindi words if you can (for example have Gemini answer in Devanagari + English); romanised Hinglish is sent as-is and may sound worse.
- **Which `language_code` for Hinglish is not documented.** Sarvam does not say what an `enhi` voice expects, so `hi-IN` is our (unverified) default, editable via `SARVAM_LANGUAGE_HINGLISH` (try `en-IN`).
- **Numbers:** Sarvam recommends commas in numbers over four digits (`10,000`). v3/v4-flash normalise English words and numbers automatically, so we do not send `enable_preprocessing`.
- Pace, pitch, loudness, temperature, dictionaries and voice cloning are not exposed: this phase is about reliable multilingual streaming.

### Voice-quality listening plan (the only way to know)

Automated tests prove the plumbing. Whether Hindi or Hinglish *sounds natural* can only be judged by listening, and **no real Sarvam call has been made by us**, so no quality claim is made here.

```powershell
cd VoiceAgent
$env:TTS_PROVIDER = "sarvam"; $env:RUN_TTS_SMOKE = "1"
python -m pytest tests/test_tts_smoke.py -v -s
Remove-Item Env:TTS_PROVIDER, Env:RUN_TTS_SMOKE
start tts_samples\sarvam-english.mp3; start tts_samples\sarvam-hindi.mp3; start tts_samples\sarvam-hinglish.mp3
```

It makes three short billable calls and writes `tts_samples/<provider>-<language>.mp3` (git-ignored; override with `TTS_SMOKE_DIR`). Output shows only status, bytes, time to first chunk and total time. Run it again with `TTS_PROVIDER=deepgram` to compare.

| Language | Phrase (fixed in the test) | Listen for |
|---|---|---|
| English | "Hello! I can help you book an appointment and answer your questions." | Clear, natural pacing; the Indian-English voice should not sound robotic. |
| Hindi | "नमस्ते! मैं आपकी मदद कर सकता हूँ। आप क्या जानना चाहते हैं?" | Correct Devanagari pronunciation (नमस्ते, मदद, हूँ), natural sentence rhythm and pauses at `।` and `?`. |
| Hinglish | "Namaste! Main aapki appointment book karne mein help kar sakta hoon." | Hindi words (Main, aapki, karne, mein, sakta, hoon) read with Hindi, not English, phonetics; English words (appointment, book, help) read naturally; smooth switching. |

Rate each file (good / acceptable / poor) and note it in your own records. If Hinglish is poor, try in this order: `SARVAM_LANGUAGE_HINGLISH=en-IN`; another `*_enhi_*` speaker via `SARVAM_SPEAKER_HINGLISH`; sending the same sentence with Devanagari Hindi words; `bulbul:v3`.

### Timeouts, cancellation and concurrency

| Limit | Setting (default) | When exceeded |
|---|---|---|
| Wait for the provider to connect, and for each next audio chunk | `TTS_TIMEOUT_SECONDS` (15) | `504 tts_timeout` (before audio) or an aborted stream |
| Whole synthesis | `TTS_STREAM_TIMEOUT_SECONDS` (60) | same |
| Client too slow to accept a chunk | `TTS_SEND_TIMEOUT_SECONDS` (10) | stream dropped, upstream closed |
| Simultaneous syntheses | `TTS_MAX_CONCURRENT_REQUESTS` (4), own limiter, independent of Gemini and STT | `503 tts_capacity_reached` after waiting `TTS_QUEUE_TIMEOUT_SECONDS` (2) |
| Text length | `TTS_MAX_TEXT_CHARS` (2000) | `422 tts_text_too_long` |

- **Errors before audio starts** are normal JSON errors with a real status: `503 tts_not_configured`, `422 tts_invalid_voice` / `tts_text_too_long` / `validation_error`, `502 tts_authentication_failed` (401/403), `429 tts_rate_limited` (429 or 402), `504 tts_timeout`, `503 tts_unavailable`, `502 tts_bad_response` (empty audio or a non-audio reply), `502 tts_provider_error`, `503 tts_capacity_reached`. Provider error bodies are never read or forwarded.
- **A failure after audio started** cannot change the `200`. The connection is **aborted** (the final chunk is never sent), so the client sees a truncated download, never audio that looks complete.
- **Client disconnect:** the server cancels synthesis, closes the upstream connection and frees the slot, in that order, on every path (success, error, timeout, cancel). Nothing is spooled to disk.
- **Privacy:** text, audio, API keys and provider error bodies are never logged or returned. One metadata line per request: outcome, language, voice, text length, byte and chunk counts, time to first audio, total time.
- Like `/chat`, **the endpoint has no authentication yet** and spends provider credit: keep it on `127.0.0.1`.

### What was tested, and what was not

- **Offline (normal suite):** a fake provider covers progressive chunks, headers, validation, voices, missing key, every failure class, empty/non-audio replies, mid-stream failure, timeouts, disconnects, stalled clients, concurrency and slot release, request IDs, security headers and log leakage. Both HTTP providers are tested against a mocked transport: the exact request (URL, auth header, per-language `language_code`/`speaker`, unchanged English, Devanagari and romanised-Hinglish text), status mapping, early close, configuration validation and provider switching. Progressive delivery is also verified through a real local Uvicorn server over real sockets.
- **NOT tested: any real provider call, and every claim about how Hindi or Hinglish sounds.** The opt-in smoke test above is ready for you.

## Voice turns: `WS /voice/stream` (Phase 4, step 1)

The first end-to-end pipeline: **the user's words in (typed text, or raw PCM16 audio) -> Gemini streaming reply -> the reply spoken sentence by sentence (Deepgram or Sarvam TTS)**. It composes the existing services in-process (Deepgram STT provider, `ChatService.stream`, `TtsService`) and changes none of `/health`, `/chat`, `/chat/stream`, `/stt/stream` or `/tts/stream`.

**Not in this step:** the browser microphone (`AudioWorklet`, resampling, playback) and the frontend. Audio input is raw PCM16 over the socket, tested here with WAV recordings. One connection carries **one turn**; barge-in and multi-turn sockets come later.

```
audio turn:  client PCM16 ──> Deepgram STT ──(finals joined)──> Gemini stream ──> sentences ──> TTS ──> client MP3
text turn:   client text  ───────────────────────────────────> Gemini stream ──> sentences ──> TTS ──> client MP3
                                                              └──> reply_text events (the text, as it is produced)
```

Each finished sentence goes to TTS **as soon as it is complete**, while Gemini keeps generating. A bounded queue (`VOICE_SENTENCE_QUEUE_SIZE`) sits between them: if speech is slower than Gemini, Gemini waits instead of buffering without limit.

### Protocol

**Client -> server**

1. First, one **text** frame: `{"type":"config","language":"hinglish","session_id":"optional","sample_rate":16000}`
   - `language`: `english`, `hindi` or `hinglish` (default `hinglish`). It selects the STT mode, Gemini's language rule and the TTS voice.
   - `session_id`: optional (`A-Z a-z 0-9 _ -`, 1-64 chars); reuse it to continue a conversation (the same in-memory sessions as `/chat`). A random id is generated and returned if omitted.
   - `sample_rate`: **required only for audio** (`8000, 16000, 22050, 24000, 44100, 48000`); `encoding` (`"linear16"`) and `channels` (`1`) are optional. Types are strict and unknown fields are rejected.
2. Then **either**
   - one **text** frame `{"type":"text","text":"Namaste, kaise ho?"}` (1-2000 characters, non-blank), **or**
   - **binary** frames of raw mono PCM16 (little-endian, **no WAV header**: a WAV header sent as PCM is rejected), then one **text** frame `{"type":"end"}`. Audio rules are those of `/stt/stream` (whole samples, at most `STT_MAX_CHUNK_BYTES` per frame, real-time pacing, `STT_MAX_AUDIO_SECONDS`).
3. Closing the connection at any time cancels the turn. After the request, further client messages are ignored.

**Server -> client** (JSON text frames with a `type`, plus binary frames of MP3)

```json
{"type":"ready","request_id":"…16 hex…","session_id":"…","language":"hinglish","sample_rate":16000}
{"type":"partial","seq":1,"text":"namaste"}
{"type":"final","seq":2,"text":"namaste duniya","start":0.0,"duration":1.2,"speech_final":true,"confidence":0.97}
{"type":"reply_text","text":"Namaste! "}
{"type":"audio_start","index":0,"content_type":"audio/mpeg"}
<binary frame: MP3 bytes of sentence 0> …
{"type":"audio_end","index":0,"complete":true,"bytes":23456}
{"type":"error","stage":"tts","code":"tts_unavailable","message":"…","request_id":"…","fatal":false}
{"type":"done","request_id":"…","session_id":"…","model":"…","language":"hinglish","audio_complete":true,"sentences":3,"audio_bytes":70368,"first_text_ms":1210.4,"first_audio_ms":2650.9,"transcript_ms":1850.2,"total_ms":5120.7}
```

| Event | Meaning |
|---|---|
| `ready` | Config accepted and the Gemini and TTS providers are configured. `sample_rate` is `null` for text. |
| `partial`, `final` | Audio input only; **exactly the events of `WS /stt/stream`** (`seq` increases across both). The finals, joined with spaces in order, are the message sent to Gemini. Nothing is translated or rewritten. |
| `reply_text` | A piece of Gemini's reply, sent as soon as it exists. Concatenate all of them to get the reply. |
| `audio_start` / binary / `audio_end` | One spoken sentence = one complete MP3 segment. Binary frames always belong to the **most recent** `audio_start`; `reply_text` events may arrive between them. `complete:false` means that sentence's speech failed part-way. Play segments in `index` order, each as its own audio blob (separate MP3 files joined into one stream can glitch in browsers). |
| `error` | `stage` is `stt`, `llm`, `tts`, `protocol` or `server`; only a safe `code`/`message` (and `details` listing field names for bad input, never the values). **`fatal:true` ends the turn; `fatal:false` is a warning** (only `tts` errors are non-fatal). |
| `done` | Success. `audio_complete:false` means speech failed part-way (see below). `transcript_ms` is `null` for text turns. |

**Terminal events.** A turn ends with **exactly one** of `done` or an `error` with `fatal:true`; the socket then closes (1000 after `done`; see the codes below after an error). They never both appear.

### When speech fails

If TTS fails during a turn (a rate limit, a network error, one bad sentence...), the server sends **one** non-fatal `error` with `stage:"tts"`, stops speaking, **keeps delivering Gemini's reply text**, lets Gemini finish so the reply is **stored in the conversation history**, and ends with `done` and `audio_complete:false`. A sentence that was already playing is closed with `audio_end` `complete:false`. If Gemini itself fails, the turn ends with a fatal `llm` error and the unfinished reply is **not** stored (exactly like `/chat/stream`). Missing Gemini or TTS credentials are fatal before any work is done (`llm_not_configured`, `tts_not_configured`).

### Try it with a WAV recording

Needs the service running and `GEMINI_API_KEY`, a TTS key (`TTS_PROVIDER`) and, for audio, `DEEPGRAM_API_KEY`. **This makes real, billable calls.** The recording must be mono 16-bit PCM WAV (see `recordings/`); the script strips the header and sends raw samples:

```powershell
@'
import asyncio, json, sys, wave, websockets

async def main(path, language):
    wav = wave.open(path)
    assert wav.getnchannels() == 1 and wav.getsampwidth() == 2, "need mono 16-bit PCM WAV"
    rate, segments = wav.getframerate(), {}
    async with websockets.connect("ws://127.0.0.1:8001/voice/stream", max_size=2**22) as ws:
        await ws.send(json.dumps({"type": "config", "language": language, "sample_rate": rate}))

        async def listen():
            async for message in ws:
                if isinstance(message, bytes):
                    segments[max(segments)] += message
                    continue
                event = json.loads(message)
                if event["type"] == "audio_start":
                    segments[event["index"]] = b""
                print(event["type"], event.get("text", event.get("code", "")))
        listener = asyncio.create_task(listen())

        step = int(rate * 0.02)                    # 20 ms frames, paced like a live microphone
        while frames := wav.readframes(step):      # readframes() returns raw samples, never the WAV header
            await ws.send(frames)
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "end"}))
        await listener
    for index, audio in sorted(segments.items()):
        open(f"voice-reply-{index}.mp3", "wb").write(audio)   # play them in order

asyncio.run(main(sys.argv[1], sys.argv[2]))
'@ | python - recordings\hinglish.wav hinglish
```

A text turn is the same without audio: send `{"type":"text","text":"..."}` instead of the frames and `end`.

### Limits, timeouts and cancellation

| Limit | Setting (default) | When exceeded |
|---|---|---|
| Simultaneous voice turns | `VOICE_MAX_CONCURRENT_TURNS` (4) | `voice_capacity_reached`, close 1013 (retry later) |
| Response phase: from the moment the user's text is known (typed, or transcribed) until the last audio is sent | `VOICE_TURN_TIMEOUT_SECONDS` (90) | fatal `voice_turn_timeout`, close 1011 |
| Finished sentences waiting for TTS | `VOICE_SENTENCE_QUEUE_SIZE` (3) | Gemini waits (backpressure) |
| Longest piece sent to TTS in one request | `VOICE_MAX_SENTENCE_CHARS` (300; never more than `TTS_MAX_TEXT_CHARS`) | a longer sentence is split at a clause mark or space |
| Waiting for a client message (also after the config) | `STT_IDLE_TIMEOUT_SECONDS` (8) | fatal `voice_idle_timeout`, close 1008 |
| Slow client | `STT_SEND_TIMEOUT_SECONDS` (10) | turn dropped, everything released |
| Listening to audio | the `STT_*` limits (`STT_MAX_AUDIO_SECONDS`, `STT_MAX_STREAM_SECONDS`, ...) | `stt_limit_exceeded` etc. |

Each stage keeps its **own** limiter (`STT_MAX_CONCURRENT_STREAMS`, `LLM_MAX_CONCURRENT_GENERATIONS`, `TTS_MAX_CONCURRENT_REQUESTS`); a voice turn holds an STT slot only while transcribing (released before Gemini starts), a Gemini slot and the session lock while Gemini streams, and one TTS slot per sentence. Browser origins are checked against `STT_ALLOWED_ORIGINS`.

On a client disconnect, a failure, a timeout or a cancellation, three supervised tasks (Gemini, speech, a disconnect watcher) are cancelled and awaited, and the STT session, the Gemini stream and the TTS upstream are closed, then every slot is released, in that order, on every path. An unfinished reply is not stored in the history.

### Errors

| `stage` | `code` | Close | Meaning |
|---|---|---|---|
| `protocol` | `voice_invalid_config` | 1008 | Bad config (unknown field, bad language, session id, sample rate...), or audio without `sample_rate`. |
| `protocol` | `voice_invalid_message` | 1008 | Not a valid `text` message, or something other than audio frames / `end`. |
| `protocol` | `voice_idle_timeout` | 1008 | No client message for `STT_IDLE_TIMEOUT_SECONDS`. |
| `stt` | `stt_*` | 1008-1011 | Same codes as `/stt/stream`: `stt_not_configured`, `stt_invalid_audio` (also a WAV header), `stt_limit_exceeded`, `stt_authentication_failed`, `stt_rate_limited`, `stt_timeout`... |
| `stt` | `voice_no_speech` | 1000 | No speech was recognised. Gemini is not called. |
| `stt` | `voice_transcript_too_long` | 1009 | The transcript exceeds 2000 characters. It is rejected, never truncated. |
| `llm` | `llm_*`, `session_busy`, `generation_capacity_reached` | 1011 | Same codes as `/chat/stream`. |
| `tts` | `tts_*` | n/a | Non-fatal (`fatal:false`), except `tts_not_configured`, which is fatal before any work. |
| `server` | `voice_capacity_reached` | 1013 | `VOICE_MAX_CONCURRENT_TURNS` turns are active. |
| `server` | `voice_turn_timeout`, `internal_error` | 1011 | Turn timeout, or an unexpected error (details only in the server log, never the message text). |

### Privacy

Never logged or returned: API keys, the user's text, transcripts, Gemini's reply, audio, or provider error text. One metadata line per turn: outcome, failing stage, error code, mode (`text`/`audio`), language, counts of sentences and bytes, and timings.

### What was tested, and what was not

- **Offline (normal suite, fake STT, Gemini and TTS providers):** the full text and audio turns; exact event order and content; the sentence chunker (English, Devanagari `।`, Hinglish, decimals, abbreviations, any streaming granularity); first-sentence audio before Gemini finishes; the bounded queue; speech failing on the first/second sentence/mid-sentence with one terminal event and consistent history; Gemini failing before/during the reply; missing credentials; every protocol error; WAV headers and bad frames; no speech; disconnects during listening, generating and speaking; turn timeout; the concurrency limit and slot release; stalled clients; log privacy; configuration.
- **Offline over real sockets:** a real Uvicorn server and a real WebSocket client verify progressive delivery of binary audio and that sentence 1 is heard before Gemini produces sentence 2.
- **NOT tested: any real provider call through this endpoint** (Deepgram, Gemini, Sarvam), real latency, or how Hindi/Hinglish sounds. Live runs are billable and must be started by you.

## Conversation sessions

History is kept per `session_id` **in memory only**, shared by `/chat` and `/chat/stream`:

- Bounded by turns, characters, number of sessions and idle time. Beyond `SESSION_MAX_SESSIONS` the least recently used idle session is evicted; a session that is mid-request is never evicted.
- A reply is added to the history only after it was generated successfully and completely. Failed, timed-out, empty or cancelled generations leave the history exactly as it was.
- **Nothing is written to disk or a database. Sessions are lost on restart and are not shared between worker processes**, so run a single worker until a shared store is justified.

## Security (read this before exposing the service)

- **`POST /chat`, `POST /chat/stream`, `WS /stt/stream`, `POST /tts/stream` and `WS /voice/stream` have no authentication yet and spend your Gemini / Deepgram quota.** Treat them as local-development only: keep `--host 127.0.0.1`, do not expose port 8001 to a network, and put no secrets in prompts or audio. Anyone who can reach them can use your keys and continue any chat session whose ID they know. (The STT origin allow-list only stops other web pages from using your browser to reach it.)
- The service-to-service authentication contract (short-lived signed tokens carrying a Backend-verified user and agent, never client-supplied identity) is designed below but **not implemented**. It must be built before this service is reachable by anyone but the Backend.
- Never logged or returned: the API key, message text, replies, session IDs, provider error messages, exception messages. Logs hold only metadata (model, timings, outcome, counts, status codes, request IDs).

### Service-to-service authentication (design, not implemented)

1. The Backend authenticates the user and verifies they own the agent (its database is the source of truth).
2. The Backend calls the VoiceAgent with a short-lived signed token (JWT, `aud="awaazai-voiceagent"`, `exp` <= 60 s, unique `jti`) containing the verified `user_id` and `agent_id`, plus the agent configuration to run.
3. The VoiceAgent verifies signature, audience and expiry and uses only those claims; it rejects anything else.
4. The shared secret lives in each service's environment (never in code or the frontend) and must be rotatable.
5. Browser audio sessions will use a one-time, short-lived session token minted by the Backend.

## Current limitations

- No authentication (above); single process only; in-memory sessions.
- Gemini streaming is HTTP SSE (one request per message); there is no mid-stream "stop" other than closing the connection.
- Reverse proxies must not buffer or compress `text/event-stream` (`X-Accel-Buffering: no` is sent; configure other proxies yourself).
- Gemini latency and availability vary by model and time (see the model note); the service reports them, it cannot fix them.
- Whether Google stops billing/generating after an abandoned stream is outside what the client can observe.
- `WS /voice/stream` connects STT, Gemini and TTS, but one turn per connection, no barge-in, no browser microphone or playback code yet, and every spoken sentence is a separate MP3 segment. It has only been tested offline with fake providers: no real end-to-end run, latency measurement or listening test has been done. Sarvam says romanised Hindi lowers quality, and the Hinglish prompt still asks Gemini for Roman script (not changed in this step).
- TTS: Deepgram has no Hindi voice (use `TTS_PROVIDER=sarvam`). Sarvam's Hindi and Hinglish quality, and which `language_code` suits its `enhi` voices, are **unverified by us**: no real provider call has been made. Sarvam says romanised Hindi lowers quality and we do not transliterate. Real calls happen only in the opt-in smoke test.
- STT: mono 16-bit PCM only; real Deepgram STT has not been tested by us. Hindi and Hinglish accuracy, and the output script of Hindi words, are unverified; Deepgram documents no Roman-script Hindi mode for Nova-3, so romanised Hinglish may need a different STT provider if your measurements are poor; Deepgram needs continuous audio (it closes after ~10 s of silence).

## Connect the Backend

Add to `Backend/.env` (the Backend is not modified by this service): `VOICE_AGENT_BASE_URL=http://localhost:8001`, restart it, then call `GET /api/v1/voice-agent/status`. The Backend currently only calls `GET /health`.

## The `/health` contract

`GET /health` -> `200 application/json`: `{"status": "ok", "service": "awaazai-voiceagent", "version": "0.1.0", "environment": "development"}`. Liveness only, intentionally unauthenticated, never contains secrets or calls Gemini.

## Layout

```
app/
  main.py              create_app(): wiring, middleware, error handlers, lifespan
  config.py            validated settings
  schemas.py           /chat and /chat/stream request model, /chat response model
  prompts.py           system instructions per language
  chat_service.py      chat() and stream(): session history + limits + provider calls + timing
  streaming.py         SSE events, wire format, EventStreamResponse (owns cleanup)
  limits.py            GenerationLimiter (bounded concurrent generations)
  sessions.py          bounded in-memory sessions with per-session locks
  llm/base.py          provider-independent LLMProvider interface (generate + stream)
  llm/gemini.py        Gemini implementation (google-genai, async, producer-task streaming)
  errors.py            structured errors + handlers
  security_headers.py  headers + request id
  routes/health.py, routes/chat.py, routes/stt.py, routes/tts.py, routes/voice.py
  stt/base.py          provider-independent STT interface (AudioFormat, TranscriptEvent, STTProvider)
  stt/protocol.py      client config message + server event schemas for WS /stt/stream
  stt/deepgram.py      Deepgram live streaming client (documented WebSocket protocol)
  stt/service.py       stream orchestration: validation, limits, timeouts, cleanup
  tts/base.py          provider-independent TTS interface (TTSProvider)
  tts/http.py          shared httpx audio streaming + safe status -> error mapping
  tts/deepgram.py      Deepgram Aura provider
  tts/sarvam.py        Sarvam Bulbul provider (language -> language_code + speaker)
  tts/service.py       validation, limits, timeouts, cleanup, metadata logging
  tts/response.py      AudioStreamResponse (owns cleanup; aborts on mid-stream failure)
  voice/protocol.py    WS /voice/stream client messages, server events, voice errors
  voice/sentences.py   SentenceChunker: streamed reply -> complete sentences for TTS
  voice/service.py     turn orchestration: STT -> Gemini -> bounded sentence queue -> TTS, cleanup
tests/                 offline pytest suite (+ opt-in real-Gemini and real-Deepgram STT/TTS smoke tests)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `503 llm_not_configured` | Set `GEMINI_API_KEY` in `VoiceAgent/.env`, restart. |
| `502 llm_authentication_failed` | The key is invalid, revoked or restricted. Create a new key in Google AI Studio. |
| `502 llm_model_unavailable` | Change `GEMINI_MODEL` (see the model note), restart. |
| `429 llm_rate_limited` | Quota reached: wait, or use a billed project. |
| `504 llm_timeout` / `error` event `llm_timeout` | The model was slow or hung. Try another `GEMINI_MODEL`; raise `LLM_TIMEOUT_SECONDS` only if you accept long silences. |
| `503 generation_capacity_reached` | Too many simultaneous generations: raise `LLM_MAX_CONCURRENT_GENERATIONS` or retry. |
| All events arrive at once | A proxy or client is buffering. Use `curl.exe -N`; behind nginx keep `X-Accel-Buffering: no`; disable compression for `text/event-stream`. |
| Conversation "forgets" | Different `session_id`, TTL expired, service restarted, or more than one worker. |
| `error while attempting to bind ... 8001` | Port in use: `Get-NetTCPConnection -LocalPort 8001`. |
| Service exits with `ValidationError` | An invalid value in `.env` (for example `LLM_TIMEOUT_SECONDS=0`). |
| `tts_not_configured` on `/tts/stream` | Set the key of the selected `TTS_PROVIDER` (`DEEPGRAM_API_KEY` or `SARVAM_API_KEY`) in `VoiceAgent/.env`, restart. |
| `tts_invalid_voice` | Use `default`, or add the voice id to `DEEPGRAM_TTS_VOICES` / `SARVAM_TTS_VOICES` (the allowlist follows `TTS_PROVIDER`). |
| Hindi text sounds wrong or fails | Expected with Deepgram (no Hindi voice): set `TTS_PROVIDER=sarvam`. With Sarvam, follow the listening plan. |
| Sarvam `502 tts_provider_error` / `422` upstream | Usually a speaker that does not belong to `SARVAM_TTS_MODEL` (v3 names vs v4-flash ids) or an unsupported `SARVAM_LANGUAGE_*`. |
| Downloaded MP3 is cut short | The stream failed mid-way (the connection is aborted on purpose); check the server log line `tts stream finished`. |
| `voice_capacity_reached` on `/voice/stream` | `VOICE_MAX_CONCURRENT_TURNS` turns are active: retry, or raise the limit. |
| `/voice/stream` error with `stage:"tts"` but the text arrived | Speech failed, the reply was still delivered and stored (`done.audio_complete:false`). See the `code`. |
| `voice_no_speech` | The recording was silent or too quiet; Gemini was not called. |
| `stt_invalid_audio` on `/voice/stream` | You sent a WAV file's bytes: send raw PCM16 samples without the header. |
| `stt_not_configured` on `/stt/stream` | Set `DEEPGRAM_API_KEY` in `VoiceAgent/.env`, restart. |
| `stt_authentication_failed` | Deepgram rejected the key: check it in the Deepgram console. |
| `stt_idle_timeout` | Keep streaming frames (silence is fine); a gap of more than `STT_IDLE_TIMEOUT_SECONDS` ends the stream. |
| `stt_invalid_audio` right after connecting | You are sending something other than raw mono 16-bit PCM (for example a WAV header, stereo, or Float32). |
| Browser connection refused with 403 | The page's origin is not in `STT_ALLOWED_ORIGINS`. |
| Hinglish transcribed in the wrong language or script | Expected risk of `multi`: try `DEEPGRAM_LANGUAGE_HINGLISH=hi` or `en-IN`, or `DEEPGRAM_ENDPOINTING_MS_HINGLISH=300`, and measure with the evaluation cases. |
