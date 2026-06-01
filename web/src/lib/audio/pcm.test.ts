import { describe, expect, it } from "vitest";

import { downsampleTo16kInt16, mixMonoFloat32, TARGET_SAMPLE_RATE } from "./pcm";

describe("downsampleTo16kInt16", () => {
  it("decimates 48 kHz to 16 kHz (one third the samples)", () => {
    const input = new Float32Array(48000).fill(0.5);
    const out = downsampleTo16kInt16(input, 48000);
    expect(out.length).toBe(16000);
    expect(out[0]).toBeGreaterThan(0);
  });

  it("converts (no resample) when already 16 kHz, clamping the rails", () => {
    const out = downsampleTo16kInt16(new Float32Array([0, 1, -1]), 16000);
    expect(out.length).toBe(3);
    expect(out[0]).toBe(0);
    expect(out[1]).toBe(32767);
    expect(out[2]).toBe(-32768);
  });

  it("clamps out-of-range samples", () => {
    const out = downsampleTo16kInt16(new Float32Array([2, -2]), 16000);
    expect(out[0]).toBe(32767);
    expect(out[1]).toBe(-32768);
  });

  it("exposes the 16 kHz target", () => {
    expect(TARGET_SAMPLE_RATE).toBe(16000);
  });
});

describe("mixMonoFloat32", () => {
  it("returns the single buffer unchanged", () => {
    const a = new Float32Array([0.1, 0.2]);
    expect(mixMonoFloat32([a])).toBe(a);
  });

  it("sums two buffers with soft clipping", () => {
    const a = new Float32Array([0.6, 0.5]);
    const b = new Float32Array([0.6, -0.5]);
    const out = mixMonoFloat32([a, b]);
    expect(out[0]).toBe(1);
    expect(out[1]).toBeCloseTo(0);
  });

  it("returns an empty buffer for no input", () => {
    expect(mixMonoFloat32([]).length).toBe(0);
  });
});
