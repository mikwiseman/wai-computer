// Realtime PCM recorder worklet: buffers the mic's mono Float32 input and posts
// ~100 ms chunks to the main thread, which downsamples to 16 kHz Int16 and
// streams them to the transcription proxy. Dependency-free — AudioWorklets run
// in an isolated scope and cannot import modules.
class RealtimePcmRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this._chunks = [];
    this._frames = 0;
    // `sampleRate` is a global in the AudioWorklet scope (the context rate).
    this._chunkFrames = Math.floor(sampleRate * 0.1);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    this._chunks.push(new Float32Array(channel));
    this._frames += channel.length;

    if (this._frames >= this._chunkFrames) {
      const merged = new Float32Array(this._frames);
      let offset = 0;
      for (const chunk of this._chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      this.port.postMessage(merged, [merged.buffer]);
      this._chunks = [];
      this._frames = 0;
    }
    return true;
  }
}

registerProcessor("realtime-pcm-recorder", RealtimePcmRecorder);
