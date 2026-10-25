import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createBrowserPlayerFactory, PlaybackQueue } from './playbackQueue.js'
import { blobBytes, makePlayerHarness, tick } from './testHarness.js'

function setup() {
  const harness = makePlayerHarness()
  const statuses = []
  let idle = 0
  const queue = new PlaybackQueue({
    createPlayer: harness.createPlayer,
    onSegmentState: (index, status) => statuses.push([index, status]),
    onIdle: () => idle++,
  })
  const segment = (index, bytes, { complete = true } = {}) => {
    queue.startSegment(index, 'audio/mpeg')
    for (const chunk of bytes) queue.appendFrame(chunk)
    queue.endSegment(index, complete)
  }
  return { harness, statuses, queue, segment, idle: () => idle }
}

test('completed segments play in index order, one at a time, never overlapping', async () => {
  const { harness, queue, segment } = setup()
  segment(0, [Uint8Array.of(1, 2)])
  assert.equal(harness.started.length, 1) // sentence 1 starts as soon as it is complete
  segment(1, [Uint8Array.of(3)])
  segment(2, [Uint8Array.of(4)])
  assert.equal(harness.started.length, 1, 'later sentences wait for the current one')

  harness.players[0].finish()
  await tick()
  assert.equal(harness.started.length, 2)
  harness.players[1].finish()
  await tick()
  harness.players[2].finish()
  await tick()
  assert.deepEqual(await Promise.all(harness.players.map((p) => blobBytes(p.blob))), [[1, 2], [3], [4]])
  assert.equal(harness.maxConcurrent, 1)
  assert.equal(queue.isPlaying, false)
})

test('a segment that completes before an earlier one waits for it, so order is by index', async () => {
  const { harness, segment } = setup()
  segment(1, [Uint8Array.of(11)]) // sentence 2 is complete first
  assert.equal(harness.players.length, 0, 'it must wait: sentence 1 has not arrived')
  segment(0, [Uint8Array.of(10)])
  assert.equal(harness.players.length, 1)
  assert.deepEqual(await blobBytes(harness.players[0].blob), [10])
  harness.players[0].finish()
  await tick()
  assert.deepEqual(await blobBytes(harness.players[1].blob), [11])
})

test('binary frames of one segment are joined exactly, from ArrayBuffers and Uint8Arrays alike', async () => {
  const { harness, segment } = setup()
  segment(0, [Uint8Array.of(1, 2, 3), Uint8Array.of(4).buffer, Uint8Array.of(5, 6)])
  const blob = harness.players[0].blob
  assert.equal(blob.type, 'audio/mpeg')
  assert.deepEqual(await blobBytes(blob), [1, 2, 3, 4, 5, 6])
})

test('each sentence is its own blob: segments are never concatenated into one stream', async () => {
  const { harness, segment } = setup()
  segment(0, [Uint8Array.of(1)])
  segment(1, [Uint8Array.of(2)])
  harness.players[0].finish()
  await tick()
  assert.deepEqual(await blobBytes(harness.players[0].blob), [1])
  assert.deepEqual(await blobBytes(harness.players[1].blob), [2])
})

test('a segment that failed part-way (complete:false) is skipped and does not block the next one', async () => {
  const { harness, statuses, segment } = setup()
  segment(0, [Uint8Array.of(1)], { complete: false })
  segment(1, [Uint8Array.of(2)])
  assert.equal(harness.players.length, 1)
  assert.deepEqual(await blobBytes(harness.players[0].blob), [2])
  assert.deepEqual(statuses.filter(([index]) => index === 0).map(([, status]) => status), ['receiving', 'skipped'])
})

test('an empty complete segment is skipped rather than played', () => {
  const { harness, segment } = setup()
  segment(0, [])
  assert.equal(harness.players.length, 0)
})

test('segment status goes receiving -> ready -> playing -> played', async () => {
  const { harness, statuses, segment } = setup()
  segment(0, [Uint8Array.of(1)])
  harness.players[0].finish()
  await tick()
  assert.deepEqual(statuses, [[0, 'receiving'], [0, 'ready'], [0, 'playing'], [0, 'played']])
})

test('binary frames outside an audio_start..audio_end pair are ignored and never played', () => {
  const { harness, queue } = setup()
  queue.appendFrame(Uint8Array.of(9, 9))
  assert.equal(queue.ignoredFrames, 1)
  assert.equal(harness.players.length, 0)
})

test('finish() after the turn ends plays what is complete and skips indices that never arrived', async () => {
  const { harness, queue, segment, idle } = setup()
  segment(2, [Uint8Array.of(7)]) // sentences 1 and 2 never arrived
  assert.equal(harness.players.length, 0)
  queue.finish()
  assert.equal(harness.players.length, 1)
  harness.players[0].finish()
  await tick()
  assert.equal(idle(), 1, 'onIdle fires when everything has been played')
})

test('finish() with nothing to play reports idle', () => {
  const { queue, idle } = setup()
  queue.finish()
  assert.equal(idle(), 1)
})

test('stop() silences the current sentence at once and drops everything queued', async () => {
  const { harness, queue, segment } = setup()
  segment(0, [Uint8Array.of(1)])
  segment(1, [Uint8Array.of(2)])
  queue.stop()
  assert.equal(harness.players[0].stopped, true)
  await tick()
  assert.equal(harness.players.length, 1, 'the queued sentence never starts')
  queue.startSegment(5) // late events from the cancelled turn are ignored
  queue.endSegment(5, true)
  assert.equal(harness.players.length, 1)
  assert.equal(harness.concurrent, 0)
})

test('reset() prepares the queue for a new turn after a stop', () => {
  const { harness, queue, segment } = setup()
  queue.stop()
  queue.reset()
  segment(0, [Uint8Array.of(1)])
  assert.equal(harness.players.length, 1)
})

test('a sentence that cannot be played does not stall the ones after it', async () => {
  const { harness, statuses, segment } = setup()
  segment(0, [Uint8Array.of(1)])
  segment(1, [Uint8Array.of(2)])
  harness.players[0].fail()
  await tick()
  assert.equal(harness.players.length, 2)
  assert.ok(statuses.some(([index, status]) => index === 0 && status === 'played'))
})

// ---------------------------------------------------------------- the real <audio> player

function fakeAudioElement() {
  return {
    src: '', paused: true, playCalls: 0, pauseCalls: 0,
    play() { this.playCalls++; this.paused = false; return Promise.resolve() },
    pause() { this.pauseCalls++; this.paused = true },
  }
}

test('the browser player plays a blob through one shared audio element and releases the object URL', async () => {
  const audio = fakeAudioElement()
  const urls = { created: [], revoked: [], createObjectURL(blob) { this.created.push(blob); return `blob:test/${this.created.length}` }, revokeObjectURL(url) { this.revoked.push(url) } }
  const player = createBrowserPlayerFactory(audio, urls)(new Blob([Uint8Array.of(1)], { type: 'audio/mpeg' }))
  const done = player.play()
  assert.equal(audio.src, 'blob:test/1')
  assert.equal(audio.playCalls, 1)
  audio.onended()
  await done
  assert.deepEqual(urls.revoked, ['blob:test/1'])
})

test('the browser player resolves (instead of hanging) when playback errors or is blocked', async () => {
  const audio = fakeAudioElement()
  audio.play = () => Promise.reject(new Error('NotAllowedError'))
  const urls = { createObjectURL: () => 'blob:x', revokeObjectURL() {} }
  await createBrowserPlayerFactory(audio, urls)(new Blob([])).play()

  const audio2 = fakeAudioElement()
  const done = createBrowserPlayerFactory(audio2, urls)(new Blob([])).play()
  audio2.onerror()
  await done
})

test('stopping the browser player pauses the element and settles the pending play()', async () => {
  const audio = fakeAudioElement()
  const urls = { revoked: 0, createObjectURL: () => 'blob:y', revokeObjectURL() { this.revoked++ } }
  const player = createBrowserPlayerFactory(audio, urls)(new Blob([]))
  const done = player.play()
  player.stop()
  await done
  assert.equal(audio.pauseCalls, 1)
  assert.equal(urls.revoked, 1)
})
