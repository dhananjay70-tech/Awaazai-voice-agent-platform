import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CaptureError, describeMediaError, startCapture } from './audioCapture.js'

function makeDeps({ getUserMedia, addModule, sampleRate = 48000 } = {}) {
  const log = { tracksStopped: 0, contextsClosed: 0, contextsCreated: 0, nodes: [], sources: [], modules: [] }
  const stream = { getTracks: () => [{ stop: () => log.tracksStopped++ }, { stop: () => log.tracksStopped++ }] }
  class FakeAudioContext {
    constructor() {
      log.contextsCreated++
      this.sampleRate = sampleRate
      this.state = 'running'
      this.audioWorklet = {
        addModule: async (url) => {
          log.modules.push(url)
          if (addModule) await addModule()
        },
      }
    }
    createMediaStreamSource() {
      const source = { connected: null, disconnected: false, connect(node) { this.connected = node }, disconnect() { this.disconnected = true } }
      log.sources.push(source)
      return source
    }
    async close() { this.state = 'closed'; log.contextsClosed++ }
    async resume() { this.state = 'running' }
  }
  class FakeAudioWorkletNode {
    constructor(context, name, options) {
      this.name = name
      this.options = options
      this.disconnected = false
      this.port = { onmessage: null }
      log.nodes.push(this)
    }
    disconnect() { this.disconnected = true }
  }
  return {
    log,
    deps: {
      mediaDevices: { getUserMedia: getUserMedia ?? (async () => stream) },
      AudioContext: FakeAudioContext,
      AudioWorkletNode: FakeAudioWorkletNode,
    },
  }
}

const loud = (n) => Float32Array.from({ length: n }, (_, i) => 0.4 * Math.sin(i / 7))

test('capture opens a mono microphone stream and delivers raw PCM16 frames at 16 kHz', async () => {
  const requests = []
  const { deps, log } = makeDeps({ getUserMedia: async (constraints) => { requests.push(constraints); return { getTracks: () => [] } } })
  const frames = []
  const capture = await startCapture({ onFrame: (frame) => frames.push(frame), deps })
  assert.equal(capture.sampleRate, 16000)
  assert.equal(requests[0].audio.channelCount, 1)
  assert.deepEqual(log.modules, ['/pcm-capture-worklet.js'])
  assert.equal(log.nodes[0].name, 'pcm-capture')
  assert.equal(log.sources[0].connected, log.nodes[0])

  for (let i = 0; i < 40; i++) log.nodes[0].port.onmessage({ data: loud(1024) }) // ~0.85 s at 48 kHz
  assert.ok(frames.length >= 15)
  for (const frame of frames) {
    assert.ok(frame instanceof ArrayBuffer)
    assert.equal(frame.byteLength, 1600)
    assert.notEqual(new TextDecoder().decode(frame.slice(0, 4)), 'RIFF')
  }
  await capture.stop()
})

test('stop() releases everything and returns the last partial frame', async () => {
  const { deps, log } = makeDeps()
  const frames = []
  const capture = await startCapture({ onFrame: (frame) => frames.push(frame), deps })
  log.nodes[0].port.onmessage({ data: loud(3000) }) // 1000 resampled samples: one frame plus a 200-sample remainder
  const before = frames.length
  const rest = await capture.stop()
  assert.ok(rest instanceof ArrayBuffer && rest.byteLength > 0 && rest.byteLength < 1600 && rest.byteLength % 2 === 0)
  assert.equal(log.tracksStopped, 2, 'every microphone track is stopped: the browser recording indicator goes off')
  assert.equal(log.contextsClosed, 1)
  assert.equal(log.nodes[0].disconnected, true)
  assert.equal(log.sources[0].disconnected, true)
  assert.equal(log.nodes[0].port.onmessage, null)
  assert.equal(frames.length, before)
  assert.equal(await capture.stop(), null, 'stop() is idempotent')
  assert.equal(log.tracksStopped, 2)
  assert.equal(log.contextsClosed, 1)
})

test('permission denial is reported clearly and nothing is opened', async () => {
  const denied = Object.assign(new Error('x'), { name: 'NotAllowedError' })
  const { deps, log } = makeDeps({ getUserMedia: async () => { throw denied } })
  await assert.rejects(startCapture({ onFrame() {}, deps }), (error) => {
    assert.ok(error instanceof CaptureError)
    assert.equal(error.code, 'permission_denied')
    assert.match(error.message, /permission was denied/i)
    return true
  })
  assert.equal(log.contextsCreated, 0)
})

test('other microphone errors map to actionable messages', () => {
  assert.equal(describeMediaError({ name: 'NotFoundError' }).code, 'no_microphone')
  assert.equal(describeMediaError({ name: 'NotReadableError' }).code, 'microphone_busy')
  assert.equal(describeMediaError({ name: 'SecurityError' }).code, 'permission_denied')
  assert.equal(describeMediaError(new Error('weird')).code, 'capture_failed')
})

test('an unsupported browser is reported, not crashed on', async () => {
  await assert.rejects(startCapture({ onFrame() {}, deps: { mediaDevices: null, AudioContext: class {}, AudioWorkletNode: class {} } }), { code: 'unsupported' })
  await assert.rejects(startCapture({ onFrame() {}, deps: { mediaDevices: { getUserMedia: async () => ({}) }, AudioContext: null, AudioWorkletNode: null } }), { code: 'unsupported' })
})

test('if the worklet cannot load, the microphone and the audio context are released again', async () => {
  const { deps, log } = makeDeps({ addModule: async () => { throw new Error('404') } })
  await assert.rejects(startCapture({ onFrame() {}, deps }), { code: 'capture_failed' })
  assert.equal(log.tracksStopped, 2)
  assert.equal(log.contextsClosed, 1)
})

test('an encoder failure is reported through onError instead of being swallowed', async () => {
  const { deps, log } = makeDeps()
  const errors = []
  await startCapture({ onFrame() { throw new Error('boom') }, onError: (error) => errors.push(error), deps })
  log.nodes[0].port.onmessage({ data: loud(4000) })
  assert.equal(errors.length > 0, true)
})
