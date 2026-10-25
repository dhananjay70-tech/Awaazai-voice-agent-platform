# AwaazAI Frontend: voice test page

React 19 + Vite, plain JavaScript (no TypeScript, LiveKit, Docker or Prisma, and no extra runtime dependencies).

**Status: Step 2 of the voice work.** A browser page that talks to VoiceAgent's `WS /voice/stream`: it captures the microphone, streams raw PCM16 audio, shows the transcript and Gemini's reply as they arrive, and plays the reply sentence by sentence. It is a **local test page**, not the product UI, and **real microphone-to-provider behaviour has not been verified yet** (see [What was tested](#what-was-tested-and-what-was-not)).

## Run it

```powershell
# 1) VoiceAgent (port 8001) with the keys it needs in VoiceAgent/.env: GEMINI_API_KEY, a TTS key, DEEPGRAM_API_KEY for speech input
cd C:\Users\niran\Desktop\AwaazAI\VoiceAgent
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8001 --ws-per-message-deflate false

# 2) this page (port 5173)
cd C:\Users\niran\Desktop\AwaazAI\Frontend
npm install
npm run dev          # open http://localhost:5173
```

Press **Start**, allow the microphone, speak, then press **Stop**. The transcript, the reply text and the spoken sentences appear as they arrive. **Cancel** aborts the turn (closes the socket, releases the microphone, silences playback). **New conversation** forgets the server session. You can also type a message instead of speaking, which is handy for testing the reply and playback without a microphone.

Real calls to Deepgram, Gemini and Sarvam/Deepgram TTS are **billable**: only press Start when you mean to.

## Connection, origin and security

| Topic | Behaviour |
|---|---|
| URL | `ws://127.0.0.1:8001/voice/stream` by default. Override with `VITE_VOICE_AGENT_WS_URL` in `Frontend/.env.local` (see `.env.example`). |
| Loopback only | The page **refuses any non-loopback host** (anything but `localhost`, `127.0.0.1`, `[::1]`). VoiceAgent has **no authentication yet**, so it must never be reachable from outside this machine. |
| Origin | VoiceAgent only accepts browser sockets from `STT_ALLOWED_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`). Vite is pinned to port 5173 with `strictPort`, so it fails loudly instead of silently moving to 5174, where the connection would be refused. |
| Authentication | **None is used, and none is faked.** Browsers cannot set an `Authorization` header on a WebSocket, so the Backend's header-based auth cannot protect this endpoint as it is. The signed short-lived token design in `VoiceAgent/README.md` ("Service-to-service authentication") is not implemented. Until it is, this page is for local development only. |
| Secrets | The page holds no API keys. Never put a key in a `VITE_` variable: it would be visible in the browser. |
| Microphone | Requested on Start only, released on Stop, Cancel, error or leaving the page. `getUserMedia` needs `http://localhost` or HTTPS. |

## How audio is sent

The microphone runs in an **AudioWorklet** (`public/pcm-capture-worklet.js`) at the device's native rate. `src/voice/pcm.js` resamples it to **16 kHz mono** (a streaming box-filter resampler, so tones above 8 kHz are attenuated instead of aliasing), converts it to **signed 16-bit little-endian PCM**, and sends **50 ms binary frames (1600 bytes)**. There is never a WAV header. The first message is `{"type":"config","language":...,"sample_rate":16000}` (plus `session_id` after the first turn); Stop flushes the last partial frame and sends `{"type":"end"}`; the page then keeps listening for the answer. Recording is ended automatically after 100 s (the server stops listening at 120 s).

## How speech is played

Each spoken sentence arrives as `audio_start{index}`, binary MP3 frames, `audio_end{index, complete}`. `src/voice/playbackQueue.js` buffers every sentence as its **own Blob**, plays completed sentences **in index order, one at a time, never overlapping**, skips a sentence whose speech failed part-way (`complete:false`), and never lets a missing sentence block the ones after it. Cancel and leaving the page stop the current sound immediately.

## Code map

```
src/voice/pcm.js            Float32 -> 16 kHz mono PCM16 bytes (resampler, frame batcher)
src/voice/audioCapture.js   getUserMedia + AudioWorklet, permission errors, full cleanup
src/voice/voiceProtocol.js  messages, loopback URL guard, event parsing
src/voice/voiceState.js     pure reducer: transcripts, reply, errors (fatal vs warning), metrics
src/voice/playbackQueue.js  per-sentence buffering and ordered playback
src/voice/voiceClient.js    orchestration (socket + capture + playback), injectable dependencies
src/voice/useVoiceClient.js React hook (creates and always disposes the client)
src/VoiceAgentPage.jsx      the page
public/pcm-capture-worklet.js   AudioWorklet processor
```

## Tests, lint and build

```powershell
npm test         # Node's built-in test runner: 73 tests, offline, no browser, no network, no live providers
npm run lint
npm run build
```

## What was tested, and what was not

- **Unit tests (offline):** PCM conversion (range, clipping, little-endian bytes, resampling 48 kHz and 44.1 kHz, chunk-size independence, anti-aliasing, exact 1600-byte frames, no WAV header); event handling and the state reducer (partial/final, reply text, fatal vs non-fatal errors, exactly one terminal state); ordered, non-overlapping playback (gaps, skips, failures, stop); microphone capture and cleanup (permission denied, unsupported browser, worklet failure, tracks and context released); and the whole client flow with fakes (connection failure and loss, cancel at every stage, session continuity, loopback guard, send failures, dispose).
- **Protocol check against the real server code:** the real `VoiceClient` and `PcmEncoder` were run (from Node, with a synthetic tone instead of a microphone) against the **real VoiceAgent app using its offline fake STT/Gemini/TTS providers**. A spoken turn and a typed turn on the same session completed end to end: config and 16 kHz PCM16 frames accepted, partial/final transcripts, reply text, three sentence segments played in order, `done`, clean close. No provider was called.
- **NOT tested:** a real browser, a real microphone, the real `getUserMedia`/AudioWorklet/`<audio>` APIs, real Deepgram/Gemini/Sarvam responses, latency, or how Hindi/Hinglish sounds. Mocked tests do not prove those.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not connect to the voice service" | VoiceAgent is not running on `127.0.0.1:8001`, or this page's origin is not in `STT_ALLOWED_ORIGINS` (the browser cannot tell the two apart). Use `http://localhost:5173` or `http://127.0.0.1:5173`. |
| "Microphone permission was denied" | Allow the microphone for this site (the lock icon in the address bar), then press Start again. |
| Vite says port 5173 is in use | Stop the other process; the port is pinned on purpose (origin check). |
| Socket drops right after the first audio frame (seen with **Node's built-in WebSocket client**, not in a browser) | WebSocket per-message compression (permessage-deflate) is a known weak spot of that client. MP3 is already compressed, so compression only costs CPU: start VoiceAgent with `--ws-per-message-deflate false` (as above). |
| A VoiceAgent error banner (for example `llm_not_configured`) | The key for that stage is missing in `VoiceAgent/.env`; see `VoiceAgent/README.md`. |
| No sound after a reply arrived | Browser autoplay rules: the sound plays after the Start click that began the turn. Check the tab is not muted. |
