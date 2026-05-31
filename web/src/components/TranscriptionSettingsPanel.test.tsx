import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TranscriptionSettingsPanel } from "./TranscriptionSettingsPanel";
import type { TranscriptionOptions, UserSettings } from "@/lib/types";

function makeSettings(overrides?: Partial<UserSettings>): UserSettings {
  return {
    default_language: "en",
    summary_language: "en",
    summary_style: "medium",
    summary_instructions: null,
    dictation_live_stt_provider: "deepgram",
    dictation_live_stt_model: "nova-3",
    recording_live_stt_provider: "deepgram",
    recording_live_stt_model: "nova-3",
    file_stt_provider: "deepgram",
    file_stt_model: "nova-3",
    dictation_post_filter_enabled: true,
    dictation_post_filter_provider: "openai",
    dictation_post_filter_model: "gpt-4o-mini",
    ...overrides,
  };
}

const OPTIONS: TranscriptionOptions = {
  dictation_live_stt: [
    { provider: "deepgram", model: "nova-3", label: "Deepgram Nova-3", description: "" },
  ],
  recording_live_stt: [
    { provider: "deepgram", model: "nova-3", label: "Deepgram Nova-3", description: "" },
  ],
  file_stt: [{ provider: "deepgram", model: "nova-3", label: "Deepgram Nova-3", description: "" }],
  dictation_post_filter: [],
};

describe("TranscriptionSettingsPanel", () => {
  it("renders language, summary and managed-model controls", () => {
    render(
      <TranscriptionSettingsPanel
        settings={makeSettings()}
        transcriptionOptions={OPTIONS}
        onUpdate={() => {}}
      />,
    );
    expect(screen.getByText("Default language")).toBeTruthy();
    expect(screen.getByText("Summary language")).toBeTruthy();
    expect(screen.getByText("Summary detail")).toBeTruthy();
    expect(screen.getByText("Custom instructions")).toBeTruthy();
    // Selects must reflect the stored values (regression: current code must be
    // selectable, not silently fall back to the first option).
    const [defaultLang, summaryLang, summaryStyle] = screen.getAllByRole(
      "combobox",
    ) as HTMLSelectElement[];
    expect(defaultLang.value).toBe("en");
    expect(summaryLang.value).toBe("en");
    expect(summaryStyle.value).toBe("medium");
    // Managed model label resolved from options for all three categories.
    expect(screen.getAllByText("Deepgram Nova-3").length).toBe(3);
  });

  it("patches default_language on change", async () => {
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(
      <TranscriptionSettingsPanel
        settings={makeSettings()}
        transcriptionOptions={OPTIONS}
        onUpdate={onUpdate}
      />,
    );
    const [defaultLang] = screen.getAllByRole("combobox");
    await user.selectOptions(defaultLang, "fr");
    expect(onUpdate).toHaveBeenCalledWith({ default_language: "fr" });
  });

  it("patches summary_style on change", async () => {
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(
      <TranscriptionSettingsPanel
        settings={makeSettings()}
        transcriptionOptions={OPTIONS}
        onUpdate={onUpdate}
      />,
    );
    // order: [0] default lang, [1] summary lang, [2] summary style
    const style = screen.getAllByRole("combobox")[2];
    await user.selectOptions(style, "detailed");
    expect(onUpdate).toHaveBeenCalledWith({ summary_style: "detailed" });
  });

  it("commits custom instructions on blur only when changed", async () => {
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(
      <TranscriptionSettingsPanel
        settings={makeSettings()}
        transcriptionOptions={OPTIONS}
        onUpdate={onUpdate}
      />,
    );
    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "Always include action items");
    await user.tab();
    expect(onUpdate).toHaveBeenCalledWith({ summary_instructions: "Always include action items" });
  });

  it("falls back to 'provider · model' when options are unavailable", () => {
    render(
      <TranscriptionSettingsPanel
        settings={makeSettings()}
        transcriptionOptions={null}
        onUpdate={() => {}}
      />,
    );
    expect(screen.getAllByText("deepgram · nova-3").length).toBe(3);
  });
});
