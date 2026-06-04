import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { enrollVoice } from "@/lib/api";
import { OnboardingClient } from "./OnboardingClient";

const mockReplace = vi.fn();
let localStorageValues: Record<string, string>;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/api", () => ({
  enrollVoice: vi.fn(),
}));

describe("OnboardingClient", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    vi.mocked(enrollVoice).mockReset();
    localStorageValues = {};

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => localStorageValues[key] ?? null),
        setItem: vi.fn((key: string, value: string) => {
          localStorageValues[key] = value;
        }),
      },
    });
  });

  it("renders the Inbox setup prompt and allows skipping onboarding", () => {
    render(<OnboardingClient />);

    expect(screen.getByRole("heading", { level: 1, name: "Set up your universal Inbox" })).toBeInTheDocument();
    expect(screen.getByText(/recordings, files, links, notes, and Wai agent threads/i)).toBeInTheDocument();
    expect(screen.getByText("Add anything")).toBeInTheDocument();
    expect(screen.getByText("Organize once")).toBeInTheDocument();
    expect(screen.getByText("Teach your voice")).toBeInTheDocument();
    expect(localStorageValues.voice_onboarding_complete).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(localStorageValues.voice_onboarding_complete).toBe("true");
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("marks onboarding seen as soon as the user sees the screen", () => {
    render(<OnboardingClient />);

    expect(screen.getByRole("heading", { level: 1, name: "Set up your universal Inbox" })).toBeInTheDocument();
    expect(localStorageValues.voice_onboarding_complete).toBe("true");
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("surfaces microphone startup errors", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("Microphone blocked")),
      },
    });

    render(<OnboardingClient />);
    fireEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => {
      expect(screen.getByText("Microphone blocked")).toBeInTheDocument();
    });
  });

  it("records a voice sample and uploads it", async () => {
    const trackStop = vi.fn();
    const stream = {
      getTracks: () => [{ stop: trackStop }],
    } as unknown as MediaStream;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue(stream),
      },
    });

    const recorderStopSpy = vi.fn();
    class MockMediaRecorder {
      static isTypeSupported = vi.fn((mimeType: string) => mimeType === "audio/webm;codecs=opus");
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      readonly mimeType: string;

      constructor(_stream: MediaStream, options: { mimeType: string }) {
        this.mimeType = options.mimeType;
      }

      start = vi.fn();

      stop = vi.fn(() => {
        recorderStopSpy();
        this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
        this.onstop?.();
      });
    }

    Object.defineProperty(globalThis, "MediaRecorder", {
      configurable: true,
      value: MockMediaRecorder,
    });
    vi.mocked(enrollVoice).mockResolvedValue({
      person: {
        id: "person-1",
        display_name: "You",
        color: null,
        aliases: null,
        voiceprint_count: 1,
        created_at: "2026-05-18T00:00:00Z",
        updated_at: "2026-05-18T00:00:00Z",
      },
      voiceprint_id: "voiceprint-1",
      duration_s: 6,
    });

    render(<OnboardingClient />);
    fireEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Use this take" })).toBeInTheDocument();
    });

    expect(trackStop).toHaveBeenCalled();
    expect(recorderStopSpy).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Use this take" }));

    await waitFor(() => {
      expect(enrollVoice).toHaveBeenCalledWith({
        audio: expect.any(Blob),
        filename: "enrollment.webm",
      });
      expect(localStorageValues.voice_onboarding_complete).toBe("true");
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });
});
