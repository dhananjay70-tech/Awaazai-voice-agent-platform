// Audio conversion for WS /voice/stream: microphone Float32 samples -> raw mono PCM16 (little-endian) at 16 kHz.
// The server wants raw samples only: NO WAV header, a whole number of 16-bit samples per frame, real-time pacing.

export const TARGET_SAMPLE_RATE = 16000 // one of the server's allowed rates (8000-48000); 16 kHz is what STT prefers
export const FRAME_MS = 50 // server accepts at most 32768 bytes per frame; 50 ms at 16 kHz = 1600 bytes

/** Float32 samples in [-1, 1] -> Int16 samples. Out-of-range values are clipped, never wrapped. */
export function floatToPcm16(samples) {
  const out = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff)
  }
  return out
}

/** Int16 samples -> the exact bytes to send: 16-bit signed little-endian, whatever the machine's endianness. */
export function pcm16ToBytes(samples) {
  const buffer = new ArrayBuffer(samples.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < samples.length; i++) view.setInt16(i * 2, samples[i], true)
  return buffer
}

/**
 * Streaming sample-rate converter (box filter: every output sample is the average of the input it spans, which also
 * low-pass filters before decimation). Feed it chunks of any size; the result is the same as for one big chunk.
 */
export class StreamResampler {
  constructor(inputRate, outputRate = TARGET_SAMPLE_RATE) {
    if (!(inputRate > 0) || !(outputRate > 0)) throw new RangeError('sample rates must be positive')
    this.ratio = inputRate / outputRate
    this.position = 0 // where the next output sample's window starts, in samples from the start of `carry`
    this.carry = new Float32Array(0)
  }

  process(input) {
    const data = new Float32Array(this.carry.length + input.length)
    data.set(this.carry)
    data.set(input, this.carry.length)

    const out = []
    let position = this.position
    // The `1e-9` keeps floating-point rounding from delaying an output sample that is exactly complete.
    while (position + this.ratio <= data.length + 1e-9) {
      const end = Math.min(position + this.ratio, data.length)
      let sum = 0
      for (let i = Math.floor(position); i < Math.ceil(end); i++) {
        sum += data[i] * (Math.min(end, i + 1) - Math.max(position, i))
      }
      out.push(sum / this.ratio)
      position += this.ratio
    }
    const consumed = Math.min(Math.floor(position), data.length)
    this.carry = data.slice(consumed)
    this.position = position - consumed
    return Float32Array.from(out)
  }
}

/** Collects Int16 samples and hands back complete frames of exactly `samplesPerFrame` samples. */
export class FrameBatcher {
  constructor(samplesPerFrame) {
    if (!Number.isInteger(samplesPerFrame) || samplesPerFrame < 1) throw new RangeError('samplesPerFrame must be a positive integer')
    this.samplesPerFrame = samplesPerFrame
    this.pending = new Int16Array(0)
  }

  push(samples) {
    const all = new Int16Array(this.pending.length + samples.length)
    all.set(this.pending)
    all.set(samples, this.pending.length)
    const frames = []
    let offset = 0
    while (all.length - offset >= this.samplesPerFrame) {
      frames.push(all.slice(offset, offset + this.samplesPerFrame))
      offset += this.samplesPerFrame
    }
    this.pending = all.slice(offset)
    return frames
  }

  /** The leftover samples (fewer than a frame), or null if there are none. Call once when the recording ends. */
  flush() {
    if (this.pending.length === 0) return null
    const rest = this.pending
    this.pending = new Int16Array(0)
    return rest
  }
}

/** The whole microphone -> wire pipeline for one recording: Float32 chunks in, PCM16 byte buffers out. */
export class PcmEncoder {
  constructor(inputRate, { outputRate = TARGET_SAMPLE_RATE, frameMs = FRAME_MS } = {}) {
    this.outputRate = outputRate
    this.resampler = new StreamResampler(inputRate, outputRate)
    this.batcher = new FrameBatcher(Math.round((outputRate * frameMs) / 1000))
  }

  /** Returns an array of ArrayBuffers (each a whole frame), possibly empty. */
  push(floatChunk) {
    const resampled = this.resampler.process(floatChunk)
    return this.batcher.push(floatToPcm16(resampled)).map(pcm16ToBytes)
  }

  /** The final partial frame as an ArrayBuffer (a whole number of samples), or null. */
  flush() {
    const rest = this.batcher.flush()
    return rest ? pcm16ToBytes(rest) : null
  }
}
