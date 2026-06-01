// PCM helpers for realtime transcription. The proxy (Deepgram) expects raw
// 16 kHz mono LINEAR16 (signed 16-bit little-endian) audio, so we downsample
// the mic's native Float32 stream (typically 44.1/48 kHz) and convert to Int16.

export const TARGET_SAMPLE_RATE = 16000;

function clampToInt16(sample: number): number {
  const s = Math.max(-1, Math.min(1, sample));
  return Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
}

function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    out[i] = clampToInt16(input[i]);
  }
  return out;
}

/**
 * Downsample mono Float32 PCM at `srcRate` to 16 kHz Int16. Uses simple block
 * averaging (cheap anti-aliasing) when decimating. Mics are >= 16 kHz in
 * practice; if `srcRate` is already 16 kHz (or lower) we just convert.
 */
export function downsampleTo16kInt16(input: Float32Array, srcRate: number): Int16Array {
  if (!Number.isFinite(srcRate) || srcRate <= TARGET_SAMPLE_RATE) {
    return floatToInt16(input);
  }
  const ratio = srcRate / TARGET_SAMPLE_RATE;
  const outLength = Math.floor(input.length / ratio);
  const out = new Int16Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j];
      count += 1;
    }
    out[i] = clampToInt16(count > 0 ? sum / count : input[start] ?? 0);
  }
  return out;
}

/** Merge multiple mono Float32 buffers (e.g. mic + system audio) by summing
 *  with soft clipping, so a combined stream stays in [-1, 1]. */
export function mixMonoFloat32(buffers: Float32Array[]): Float32Array {
  const present = buffers.filter((b) => b.length > 0);
  if (present.length === 0) return new Float32Array(0);
  if (present.length === 1) return present[0];
  const length = Math.max(...present.map((b) => b.length));
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    let sum = 0;
    for (const buffer of present) sum += buffer[i] ?? 0;
    out[i] = Math.max(-1, Math.min(1, sum));
  }
  return out;
}
