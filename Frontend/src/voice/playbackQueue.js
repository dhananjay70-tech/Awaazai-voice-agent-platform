// Buffers each spoken sentence separately and plays the finished ones in `index` order, never overlapping.
//
// Server protocol: `audio_start{index}`, then binary MP3 frames (always the most recent audio_start's), then
// `audio_end{index, complete}`. Only complete segments are played; a segment that failed part-way
// (`complete:false`) is skipped so the queue can never stall on it. Separate MP3 files are never joined into one
// stream: each segment is its own Blob and its own playback.

/**
 * @param {(blob: Blob) => { play(): Promise<void>, stop(): void }} createPlayer  `play()` resolves when playback ends
 *        (or fails); `stop()` ends it immediately. One player is created per segment.
 * @param {(index: number, status: string) => void} onSegmentState  'receiving' | 'ready' | 'playing' | 'played' | 'skipped'
 */
export class PlaybackQueue {
  constructor({ createPlayer, onSegmentState = () => {}, onIdle = () => {} }) {
    this.createPlayer = createPlayer
    this.onSegmentState = onSegmentState
    this.onIdle = onIdle
    this.reset()
  }

  reset() {
    this.receiving = new Map() // index -> { chunks: Uint8Array[], contentType }
    this.ready = new Map() // index -> Blob of a complete segment
    this.skipped = new Set()
    this.currentIndex = null // the segment that incoming binary frames belong to
    this.nextIndex = 0
    this.player = null
    this.playing = false
    this.finished = false // the turn ended: no more segments will arrive
    this.stopped = false
    this.ignoredFrames = 0
  }

  startSegment(index, contentType = 'audio/mpeg') {
    if (this.stopped) return
    this.receiving.set(index, { chunks: [], contentType })
    this.currentIndex = index
    this.onSegmentState(index, 'receiving')
  }

  /** @param {ArrayBuffer | Uint8Array} bytes */
  appendFrame(bytes) {
    const segment = this.receiving.get(this.currentIndex)
    if (this.stopped) return
    if (!segment) {
      this.ignoredFrames++ // a binary frame outside any audio_start..audio_end: a protocol violation, never played
      return
    }
    segment.chunks.push(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes))
  }

  endSegment(index, complete) {
    if (this.stopped) return
    const segment = this.receiving.get(index)
    this.receiving.delete(index)
    if (this.currentIndex === index) this.currentIndex = null
    if (!segment || !complete || segment.chunks.length === 0) {
      this.skipped.add(index)
      this.onSegmentState(index, 'skipped')
    } else {
      this.ready.set(index, new Blob(segment.chunks, { type: segment.contentType }))
      this.onSegmentState(index, 'ready')
    }
    this.pump()
  }

  /** The turn is over: play what is complete, skipping any gaps. */
  finish() {
    if (this.stopped) return
    this.finished = true
    this.pump()
  }

  /** Cancel or leave: stop the current sound immediately and drop everything that is queued. */
  stop() {
    this.stopped = true
    if (this.player) {
      try {
        this.player.stop()
      } catch {
        /* already stopped */
      }
    }
    this.player = null
    this.playing = false
    this.receiving.clear()
    this.ready.clear()
  }

  get isPlaying() {
    return this.playing
  }

  pump() {
    if (this.playing || this.stopped) return
    // Skip over segments that will never be played (failed ones), so a gap never blocks the ones after it.
    while (this.skipped.has(this.nextIndex)) this.nextIndex++
    if (!this.ready.has(this.nextIndex)) {
      if (this.finished && this.ready.size > 0) {
        // The turn ended and indices are missing (their audio never arrived): continue with the next one we have.
        this.nextIndex = Math.min(...this.ready.keys())
      } else {
        if (this.finished && this.receiving.size === 0) this.onIdle()
        return
      }
    }
    this.playSegment(this.nextIndex)
  }

  async playSegment(index) {
    const blob = this.ready.get(index)
    this.ready.delete(index)
    this.nextIndex = index + 1
    this.playing = true
    this.onSegmentState(index, 'playing')
    const player = this.createPlayer(blob)
    this.player = player
    try {
      await player.play()
    } catch {
      /* a segment that cannot play is simply over: the next one still gets its turn */
    }
    if (this.player !== player || this.stopped) return // stop() was called meanwhile
    this.player = null
    this.playing = false
    this.onSegmentState(index, 'played')
    this.pump()
  }
}

/** The real player: one shared <audio> element (so the browser's autoplay permission from the Start click is reused). */
export function createBrowserPlayerFactory(audioElement = new Audio(), urlApi = URL) {
  return (blob) => {
    const url = urlApi.createObjectURL(blob)
    let settle = null
    const cleanup = () => {
      audioElement.onended = null
      audioElement.onerror = null
      urlApi.revokeObjectURL(url)
    }
    return {
      play() {
        return new Promise((resolve) => {
          settle = resolve
          audioElement.onended = () => {
            cleanup()
            resolve()
          }
          audioElement.onerror = () => {
            cleanup()
            resolve()
          }
          audioElement.src = url
          Promise.resolve(audioElement.play()).catch(() => {
            cleanup()
            resolve()
          })
        })
      },
      stop() {
        audioElement.pause()
        cleanup()
        if (settle) settle()
      },
    }
  }
}
