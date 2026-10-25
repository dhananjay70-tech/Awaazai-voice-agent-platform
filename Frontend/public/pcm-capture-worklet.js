// AudioWorklet processor: runs on the audio thread and forwards the microphone's raw Float32 samples (channel 0) to
// the main thread, which resamples them to 16 kHz and converts them to PCM16 (see src/voice/pcm.js).
// Served as a static file because audioWorklet.addModule() needs a URL.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel && channel.length > 0) {
      const copy = new Float32Array(channel) // the engine reuses `channel`'s memory: always copy
      this.port.postMessage(copy, [copy.buffer])
    }
    return true // keep running until the node is disconnected
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor)
