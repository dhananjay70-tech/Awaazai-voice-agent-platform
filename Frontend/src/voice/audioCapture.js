// Microphone capture: getUserMedia -> AudioWorklet -> PcmEncoder -> onFrame(ArrayBuffer of raw mono PCM16 @ 16 kHz).

import { PcmEncoder, TARGET_SAMPLE_RATE } from './pcm.js'

export const WORKLET_URL = '/pcm-capture-worklet.js'

/** A failure with a message that is safe and useful to show, plus a stable `code` for the UI and tests. */
export class CaptureError extends Error {
  constructor(code, message) {
    super(message)
    this.name = 'CaptureError'
    this.code = code
  }
}

/** Map the browser's getUserMedia errors to something a person can act on. */
export function describeMediaError(error) {
  const name = error && error.name
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
    return new CaptureError(
      'permission_denied',
      'Microphone permission was denied. Allow microphone access for this site in the browser, then press Start again.',
    )
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') {
    return new CaptureError('no_microphone', 'No microphone was found. Connect one and press Start again.')
  }
  if (name === 'NotReadableError' || name === 'TrackStartError' || name === 'AbortError') {
    return new CaptureError('microphone_busy', 'The microphone could not be opened. Another application may be using it.')
  }
  return new CaptureError('capture_failed', 'The microphone could not be started.')
}

/**
 * Start capturing. Resolves to `{ stop }` once audio is flowing; rejects with a CaptureError (nothing is left open).
 * `deps` exist so tests can supply fakes; the browser's own APIs are the defaults.
 */
export async function startCapture({
  onFrame,
  onError = () => {},
  deps = {},
}) {
  const mediaDevices = deps.mediaDevices ?? globalThis.navigator?.mediaDevices
  const AudioContextCtor = deps.AudioContext ?? globalThis.AudioContext ?? globalThis.webkitAudioContext
  const AudioWorkletNodeCtor = deps.AudioWorkletNode ?? globalThis.AudioWorkletNode

  if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
    throw new CaptureError(
      'unsupported',
      'This browser cannot capture audio here. Use a current Chrome, Edge, Firefox or Safari on http://localhost or HTTPS.',
    )
  }
  if (!AudioContextCtor || !AudioWorkletNodeCtor) {
    throw new CaptureError('unsupported', 'This browser does not support AudioWorklet, which is needed to capture audio.')
  }

  let stream = null
  let context = null
  let source = null
  let node = null
  let stopped = false

  const release = async () => {
    try {
      if (node) {
        node.port.onmessage = null
        node.disconnect()
      }
      if (source) source.disconnect()
    } catch {
      /* already disconnected */
    }
    if (stream) for (const track of stream.getTracks()) track.stop() // turns the browser's recording indicator off
    if (context && context.state !== 'closed') {
      try {
        await context.close()
      } catch {
        /* already closed */
      }
    }
  }

  try {
    stream = await mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
  } catch (error) {
    throw describeMediaError(error)
  }

  try {
    context = new AudioContextCtor() // the device's native rate: we resample ourselves (portable across browsers)
    await context.audioWorklet.addModule(deps.workletUrl ?? WORKLET_URL)
    source = context.createMediaStreamSource(stream)
    node = new AudioWorkletNodeCtor(context, 'pcm-capture', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 })
    const encoder = new PcmEncoder(context.sampleRate, { outputRate: TARGET_SAMPLE_RATE })
    node.port.onmessage = (event) => {
      if (stopped) return
      try {
        for (const frame of encoder.push(event.data)) onFrame(frame)
      } catch (error) {
        onError(error)
      }
    }
    source.connect(node)
    if (context.state === 'suspended') await context.resume()

    return {
      sampleRate: TARGET_SAMPLE_RATE,
      /** Stop capturing, release the microphone, and return the last partial frame (ArrayBuffer) or null. */
      async stop() {
        if (stopped) return null
        stopped = true
        const rest = encoder.flush()
        await release()
        return rest
      },
    }
  } catch (error) {
    stopped = true
    await release()
    if (error instanceof CaptureError) throw error
    throw new CaptureError('capture_failed', 'The audio capture could not be started.')
  }
}
