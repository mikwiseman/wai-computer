import { describe, expect, it } from "vitest";

import { applyDictionary } from "./DictatePanel";
import type { DictationDictionaryWord } from "@/lib/types";

function word(text: string, replacement: string | null): DictationDictionaryWord {
  return {
    client_word_id: text,
    word: text,
    replacement,
    occurred_at: "2026-01-01T00:00:00Z",
  };
}

describe("applyDictionary", () => {
  it("substitutes REPLACE entries (whole word, case-insensitive)", () => {
    const { text } = applyDictionary("I use wai computer daily", [
      word("wai computer", "WaiComputer"),
    ]);
    expect(text).toBe("I use WaiComputer daily");
  });

  it("does not substitute inside larger words", () => {
    const { text } = applyDictionary("rewaiwaiable", [word("wai", "X")]);
    expect(text).toBe("rewaiwaiable");
  });

  it("collects BIAS words and replacements as preserve-vocabulary", () => {
    const { vocabulary } = applyDictionary("hello", [
      word("Deepgram", null),
      word("k8s", "Kubernetes"),
    ]);
    expect(vocabulary).toContain("Deepgram");
    expect(vocabulary).toContain("Kubernetes");
  });

  it("leaves text unchanged with an empty dictionary", () => {
    const result = applyDictionary("plain text", []);
    expect(result.text).toBe("plain text");
    expect(result.vocabulary).toEqual([]);
  });
});
