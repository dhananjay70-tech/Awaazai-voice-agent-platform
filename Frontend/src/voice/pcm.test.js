import assert from 'node:assert/strict'
import { test } from 'node:test'
import { floatToPcm16, FrameBatcher, PcmEncoder, pcm16ToBytes, StreamResampler, TARGET_SAMPLE_RATE } from './pcm.js'

const sine = (freq, rate, seconds, amplitude = 0.5) =>
  Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amplitude * Math.sin((2 * Math.PI * freq * i) / rate))

const zeroCrossings = (samples) => {
  let count = 0
  for (let i = 1; i < samples.length; i++) if (samples[i - 1] < 0 !== samples[i] < 0) count++
  return count
}

test('floatToPcm16 maps the full range exactly and clips instead of wrapping', () => {
  const out = floatToPcm16(Float32Array.of(0, 1, -1, 0.5, -0.5, 2, -3.5))
  assert.deepEqual(Array.from(out), [0, 32767, -32768, 16384, -16384, 32767, -32768])
})

test('pcm16ToBytes writes signed 16-bit little-endian, two bytes per sample', () => {
  const bytes = new Uint8Array(pcm16ToBytes(Int16Array.of(1, -2, 0x1234, -32768)))
  assert.deepEqual(Array.from(bytes), [0x01, 0x00, 0xfe, 0xff, 0x34, 0x12, 0x00, 0x80])
})

test('the resampler converts 48 kHz to 16 kHz: a third of the samples, the same pitch', () => {
  const out = new StreamResampler(48000, 16000).process(sine(440, 48000, 1))
  assert.ok(Math.abs(out.length - 16000) <= 1, `length ${out.length}`)
  assert.ok(Math.abs(zeroCrossings(out) - 880) <= 2, `zero crossings ${zeroCrossings(out)}`) // 440 Hz = 880 crossings/s
  assert.ok(Math.max(...out) > 0.45 && Math.max(...out) <= 0.5, 'amplitude is preserved')
})

test('the resampler handles 44.1 kHz microphones (a non-integer ratio)', () => {
  const out = new StreamResampler(44100, 16000).process(sine(300, 44100, 1))
  assert.ok(Math.abs(out.length - 16000) <= 1)
  assert.ok(Math.abs(zeroCrossings(out) - 600) <= 2)
})

test('the resampler passes 16 kHz through unchanged', () => {
  const input = sine(200, 16000, 0.1)
  const out = new StreamResampler(16000, 16000).process(input)
  assert.equal(out.length, input.length)
  for (let i = 0; i < input.length; i++) assert.ok(Math.abs(out[i] - input[i]) < 1e-6)
})

test('the resampler removes tones above the new Nyquist limit instead of aliasing them down', () => {
  const out = new StreamResampler(48000, 16000).process(sine(21000, 48000, 0.5, 0.8)) // far above 8 kHz
  const peak = Math.max(...out.map(Math.abs))
  assert.ok(peak < 0.3, `an out-of-band tone must be attenuated, got peak ${peak}`)
})

test('feeding the resampler in tiny chunks gives the same samples as one big chunk', () => {
  const input = sine(523, 48000, 0.5)
  const whole = new StreamResampler(48000, 16000).process(input)
  const chunked = new StreamResampler(48000, 16000)
  const parts = []
  for (let i = 0; i < input.length; i += 128) parts.push(chunked.process(input.subarray(i, i + 128))) // worklet-sized chunks
  const joined = Float32Array.from(parts.flatMap((p) => Array.from(p)))
  assert.ok(Math.abs(joined.length - whole.length) <= 1)
  for (let i = 0; i < Math.min(joined.length, whole.length); i++) assert.ok(Math.abs(joined[i] - whole[i]) < 1e-5, `sample ${i}`)
})

test('FrameBatcher emits exact frames and keeps the remainder until flushed', () => {
  const batcher = new FrameBatcher(4)
  assert.deepEqual(batcher.push(Int16Array.of(1, 2, 3)), [])
  const frames = batcher.push(Int16Array.of(4, 5, 6, 7, 8, 9))
  assert.deepEqual(frames.map((f) => Array.from(f)), [[1, 2, 3, 4], [5, 6, 7, 8]])
  assert.deepEqual(Array.from(batcher.flush()), [9])
  assert.equal(batcher.flush(), null)
  assert.throws(() => new FrameBatcher(0), RangeError)
})

test('PcmEncoder produces 50 ms frames: 1600 bytes of raw PCM16 at 16 kHz, never a WAV header', () => {
  assert.equal(TARGET_SAMPLE_RATE, 16000)
  const encoder = new PcmEncoder(48000)
  const frames = []
  const input = sine(440, 48000, 1)
  for (let i = 0; i < input.length; i += 128) frames.push(...encoder.push(input.subarray(i, i + 128)))
  assert.ok(frames.length >= 19 && frames.length <= 20, `${frames.length} frames`)
  for (const frame of frames) {
    assert.ok(frame instanceof ArrayBuffer)
    assert.equal(frame.byteLength, 1600) // 800 samples x 2 bytes
    assert.equal(frame.byteLength % 2, 0)
    assert.notEqual(new TextDecoder().decode(frame.slice(0, 4)), 'RIFF')
  }
  const rest = encoder.flush()
  assert.ok(rest === null || (rest.byteLength % 2 === 0 && rest.byteLength < 1600))
})

test('silence encodes to zero samples and a quiet input stays quiet', () => {
  const encoder = new PcmEncoder(48000)
  const frames = encoder.push(new Float32Array(48000))
  assert.ok(frames.length > 0)
  for (const frame of frames) assert.ok(new Uint8Array(frame).every((byte) => byte === 0))
})

test('invalid sample rates are rejected', () => {
  assert.throws(() => new StreamResampler(0, 16000), RangeError)
  assert.throws(() => new StreamResampler(48000, -1), RangeError)
})
