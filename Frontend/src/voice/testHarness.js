// Fakes shared by the voice tests (not a test file itself): a scripted WebSocket, a player that records overlap, and a
// microphone capture whose frames the test pushes by hand.

export const tick = () => new Promise((resolve) => setImmediate(resolve))

export class FakeWebSocket {
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = 0
    this.sent = []
    this.closedWith = null
    this.binaryType = 'blob'
    FakeWebSocket.instances.push(this)
  }

  send(data) {
    if (this.readyState !== 1) throw new Error('WebSocket is not open')
    this.sent.push(data)
  }

  close(code) {
    if (this.readyState === 3) return
    this.readyState = 3
    this.closedWith = code
  }

  // ---- test controls
  open() {
    this.readyState = 1
    this.onopen?.()
  }

  receive(event) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }

  receiveRaw(data) {
    this.onmessage?.({ data })
  }

  /** The server (or network) closes the connection. */
  drop() {
    this.readyState = 3
    this.onclose?.({ code: 1006 })
  }

  get jsonSent() {
    return this.sent.filter((m) => typeof m === 'string').map((m) => JSON.parse(m))
  }

  get binarySent() {
    return this.sent.filter((m) => typeof m !== 'string')
  }
}

export function makePlayerHarness() {
  const players = []
  const harness = {
    players,
    concurrent: 0,
    maxConcurrent: 0,
    createPlayer(blob) {
      const player = { blob, ended: false, stopped: false, started: false }
      player.play = () => {
        player.started = true
        harness.concurrent++
        harness.maxConcurrent = Math.max(harness.maxConcurrent, harness.concurrent)
        return new Promise((resolve, reject) => {
          player.finish = () => {
            if (player.ended) return
            player.ended = true
            harness.concurrent--
            resolve()
          }
          player.fail = () => {
            if (player.ended) return
            player.ended = true
            harness.concurrent--
            reject(new Error('cannot play'))
          }
        })
      }
      player.stop = () => {
        player.stopped = true
        player.finish?.()
      }
      players.push(player)
      return player
    },
    get started() {
      return players.filter((p) => p.started)
    },
  }
  return harness
}

export async function blobBytes(blob) {
  return Array.from(new Uint8Array(await blob.arrayBuffer()))
}

/** A startCapture replacement. `frame(bytes)` plays the part of the microphone delivering an encoded frame. */
export function makeCaptureHarness({ rest = null, rejectWith = null, hold = false } = {}) {
  const harness = {
    started: 0,
    stops: 0,
    options: null,
    sampleRate: 16000,
    rest,
    release: null,
    frame: (bytes) => harness.options.onFrame(bytes),
    async startCapture(options) {
      harness.started++
      harness.options = options
      if (rejectWith) throw rejectWith
      if (hold) await new Promise((resolve) => { harness.release = resolve })
      return {
        sampleRate: harness.sampleRate,
        async stop() {
          harness.stops++
          return harness.stops === 1 ? harness.rest : null
        },
      }
    },
  }
  return harness
}

export const frameOf = (value, samples = 800) => new Int16Array(samples).fill(value).buffer
