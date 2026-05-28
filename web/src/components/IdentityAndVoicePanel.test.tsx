import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { IdentityAndVoicePanel } from "./IdentityAndVoicePanel";
import {
  disableVoiceSharing,
  enableVoiceSharing,
  getIdentity,
  getVoiceSharing,
  updateIdentity,
} from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getIdentity: vi.fn(),
    updateIdentity: vi.fn(),
    getVoiceSharing: vi.fn(),
    enableVoiceSharing: vi.fn(),
    disableVoiceSharing: vi.fn(),
  };
});

const mockedGetIdentity = vi.mocked(getIdentity);
const mockedUpdateIdentity = vi.mocked(updateIdentity);
const mockedGetVoiceSharing = vi.mocked(getVoiceSharing);
const mockedEnableVoiceSharing = vi.mocked(enableVoiceSharing);
const mockedDisableVoiceSharing = vi.mocked(disableVoiceSharing);

async function flushAsync() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("IdentityAndVoicePanel", () => {
  beforeEach(() => {
    mockedGetIdentity.mockResolvedValue({
      first_name: null,
      last_name: null,
      has_voiceprint: false,
    });
    mockedGetVoiceSharing.mockResolvedValue({
      enabled: false,
      can_enable: false,
      has_first_name: false,
      has_last_name: false,
      has_voiceprint: false,
      shared_name: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    cleanup();
  });

  it("loads identity + sharing state on mount", async () => {
    render(<IdentityAndVoicePanel />);
    await flushAsync();
    expect(mockedGetIdentity).toHaveBeenCalledTimes(1);
    expect(mockedGetVoiceSharing).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("identity-first-name")).toHaveValue("");
    expect(screen.getByTestId("identity-last-name")).toHaveValue("");
  });

  it("disables the sharing toggle until prerequisites are met", async () => {
    render(<IdentityAndVoicePanel />);
    await flushAsync();
    const toggle = screen.getByTestId("voice-sharing-toggle") as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.checked).toBe(false);
  });

  it("saves names on blur and refreshes sharing state", async () => {
    mockedUpdateIdentity.mockResolvedValue({
      first_name: "Anna",
      last_name: "Wise",
      has_voiceprint: true,
    });
    mockedGetVoiceSharing
      .mockResolvedValueOnce({
        enabled: false,
        can_enable: false,
        has_first_name: false,
        has_last_name: false,
        has_voiceprint: true,
        shared_name: null,
      })
      .mockResolvedValueOnce({
        enabled: false,
        can_enable: true,
        has_first_name: true,
        has_last_name: true,
        has_voiceprint: true,
        shared_name: null,
      });

    render(<IdentityAndVoicePanel />);
    await flushAsync();
    const firstField = screen.getByTestId("identity-first-name");
    fireEvent.change(firstField, { target: { value: "Anna" } });
    const lastField = screen.getByTestId("identity-last-name");
    fireEvent.change(lastField, { target: { value: "Wise" } });
    fireEvent.blur(lastField);
    await flushAsync();
    expect(mockedUpdateIdentity).toHaveBeenCalledWith({
      first_name: "Anna",
      last_name: "Wise",
    });
    const toggle = screen.getByTestId("voice-sharing-toggle") as HTMLInputElement;
    expect(toggle.disabled).toBe(false);
  });

  it("requires confirmation before turning sharing on", async () => {
    mockedGetVoiceSharing.mockResolvedValue({
      enabled: false,
      can_enable: true,
      has_first_name: true,
      has_last_name: true,
      has_voiceprint: true,
      shared_name: null,
    });
    mockedGetIdentity.mockResolvedValue({
      first_name: "Anna",
      last_name: "Wise",
      has_voiceprint: true,
    });
    mockedEnableVoiceSharing.mockResolvedValue({
      enabled: true,
      can_enable: true,
      has_first_name: true,
      has_last_name: true,
      has_voiceprint: true,
      shared_name: "Anna Wise",
    });

    render(<IdentityAndVoicePanel />);
    await flushAsync();
    const toggle = screen.getByTestId("voice-sharing-toggle");
    fireEvent.click(toggle);
    await flushAsync();

    // Confirmation dialog appears; enable shouldn't have fired yet.
    expect(screen.getByTestId("voice-sharing-confirm")).toBeTruthy();
    expect(mockedEnableVoiceSharing).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("voice-sharing-confirm-share"));
    await flushAsync();
    expect(mockedEnableVoiceSharing).toHaveBeenCalledTimes(1);
  });

  it("turns sharing off without confirmation", async () => {
    mockedGetVoiceSharing.mockResolvedValue({
      enabled: true,
      can_enable: true,
      has_first_name: true,
      has_last_name: true,
      has_voiceprint: true,
      shared_name: "Anna Wise",
    });
    mockedGetIdentity.mockResolvedValue({
      first_name: "Anna",
      last_name: "Wise",
      has_voiceprint: true,
    });
    mockedDisableVoiceSharing.mockResolvedValue({
      enabled: false,
      can_enable: true,
      has_first_name: true,
      has_last_name: true,
      has_voiceprint: true,
      shared_name: null,
    });

    render(<IdentityAndVoicePanel />);
    await flushAsync();
    fireEvent.click(screen.getByTestId("voice-sharing-toggle"));
    await flushAsync();
    expect(mockedDisableVoiceSharing).toHaveBeenCalledTimes(1);
    expect(mockedEnableVoiceSharing).not.toHaveBeenCalled();
  });
});
