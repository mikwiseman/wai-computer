import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { ApiError, apiFetch, apiUpload } from "./http";

// Mock the network layer but keep the real ApiError class so the
// withLocalhostAuth "message-without-token" branch (api.ts L74) throws a
// genuine ApiError that `instanceof` / status checks can assert against.
vi.mock("./http", async () => {
  const actual = await vi.importActual<typeof import("./http")>("./http");
  return {
    ApiError: actual.ApiError,
    apiFetch: vi.fn(),
    apiFetchResponse: vi.fn(),
    apiUpload: vi.fn(),
    syncLocalhostAuthCookie: vi.fn(),
    syncLocalhostRefreshCookie: vi.fn(),
  };
});

const mockedApiFetch = vi.mocked(apiFetch);
const mockedApiUpload = vi.mocked(apiUpload);

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockedApiFetch.mockResolvedValue({} as never);
  mockedApiUpload.mockReset();
  mockedApiUpload.mockResolvedValue({} as never);
});

describe("api auth/account extras", () => {
  it("requestPasswordReset posts email + locale", async () => {
    await api.requestPasswordReset("a@example.com", "ru");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: "a@example.com", locale: "ru" }),
    });
  });

  it("deleteAccount issues DELETE /api/auth/me", async () => {
    await api.deleteAccount();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/me", { method: "DELETE" });
  });

  it("withLocalhostAuth throws ApiError(200) when the response is a message without a token", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      message: "Check your email to finish signing in",
    } as never);

    await expect(api.login("a@example.com", "p")).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      message: "Check your email to finish signing in",
    });
  });

  it("withLocalhostAuth passes a normal token response straight through", async () => {
    const tokens = { access_token: "t", refresh_token: "r", token_type: "bearer" };
    mockedApiFetch.mockResolvedValueOnce(tokens as never);
    await expect(api.refreshToken()).resolves.toEqual(tokens);
  });

  it("withLocalhostAuth surfaces a real ApiError instance on the message branch", async () => {
    mockedApiFetch.mockResolvedValueOnce({ message: "magic-link sent" } as never);
    const err = await api.verifyMagicLink("tok").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(200);
    expect((err as ApiError).payload).toEqual({ message: "magic-link sent" });
  });
});

describe("api recording uploads + speakers", () => {
  it("uploadAudio sends the file as multipart form-data", async () => {
    const file = new File(["bytes"], "clip.m4a", { type: "audio/mp4" });
    await api.uploadAudio("rec1", file);

    expect(mockedApiUpload).toHaveBeenCalledWith(
      "/api/recordings/rec1/upload",
      expect.any(FormData),
    );
    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect(formData.get("file")).toBeInstanceOf(File);
    expect((formData.get("file") as File).name).toBe("clip.m4a");
  });

  it("getSpeakerStats hits the speaker-stats endpoint", async () => {
    await api.getSpeakerStats("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/speaker-stats");
  });

  it("assignSpeaker with an existing person id forwards the body verbatim", async () => {
    await api.assignSpeaker("rec1", { raw_label: "Speaker 1", person_id: "p-9" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/assign-speaker", {
      method: "POST",
      body: JSON.stringify({ raw_label: "Speaker 1", person_id: "p-9" }),
    });
  });

  it("assignSpeaker with a new display name forwards the body verbatim", async () => {
    await api.assignSpeaker("rec1", { raw_label: "Speaker 2", new_display_name: "Dana" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/assign-speaker", {
      method: "POST",
      body: JSON.stringify({ raw_label: "Speaker 2", new_display_name: "Dana" }),
    });
  });

  it("rematchSpeakers posts to the rematch endpoint", async () => {
    await api.rematchSpeakers("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/rematch", {
      method: "POST",
    });
  });

  it("saveTranscript posts the segments array", async () => {
    const segments = [
      { speaker: "Speaker 1", text: "hello", start: 0, end: 1.2 },
    ];
    await api.saveTranscript("rec1", segments as never);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/transcript", {
      method: "POST",
      body: JSON.stringify({ segments }),
    });
  });
});

describe("api people CRUD", () => {
  it("listPeople reads /api/people", async () => {
    await api.listPeople();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/people");
  });

  it("createPerson posts the provided fields", async () => {
    await api.createPerson({ display_name: "Ada", color: "#abc", aliases: ["A"] });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/people", {
      method: "POST",
      body: JSON.stringify({ display_name: "Ada", color: "#abc", aliases: ["A"] }),
    });
  });

  it("updatePerson patches the person by id", async () => {
    await api.updatePerson("p-1", { display_name: "Grace" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/people/p-1", {
      method: "PATCH",
      body: JSON.stringify({ display_name: "Grace" }),
    });
  });

  it("deletePerson issues a DELETE", async () => {
    await api.deletePerson("p-1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/people/p-1", { method: "DELETE" });
  });

  it("mergePeople posts the target into_person_id", async () => {
    await api.mergePeople("source-1", "target-2");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/people/source-1/merge", {
      method: "POST",
      body: JSON.stringify({ into_person_id: "target-2" }),
    });
  });
});

describe("api transcription session + voice enrollment", () => {
  it("createTranscriptionSession applies defaults (multi / recording)", async () => {
    await api.createTranscriptionSession();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/transcription/session", {
      method: "POST",
      body: JSON.stringify({ language: "multi", channels: 1, purpose: "recording" }),
    });
  });

  it("createTranscriptionSession honours explicit language + purpose", async () => {
    await api.createTranscriptionSession({ language: "en", purpose: "dictation" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/transcription/session", {
      method: "POST",
      body: JSON.stringify({ language: "en", channels: 1, purpose: "dictation" }),
    });
  });

  it("enrollVoice uploads audio with a default filename and no optional fields", async () => {
    const audio = new Blob(["wav"], { type: "audio/wav" });
    await api.enrollVoice({ audio });

    expect(mockedApiUpload).toHaveBeenCalledWith("/api/voice-enrollment", expect.any(FormData));
    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect(formData.get("audio")).toBeInstanceOf(File);
    expect((formData.get("audio") as File).name).toBe("enrollment.wav");
    expect(formData.get("display_name")).toBeNull();
    expect(formData.get("person_id")).toBeNull();
  });

  it("enrollVoice forwards filename, display_name and person_id when given", async () => {
    const audio = new Blob(["wav"], { type: "audio/wav" });
    await api.enrollVoice({
      audio,
      filename: "voice.wav",
      display_name: "Linus",
      person_id: "p-7",
    });

    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect((formData.get("audio") as File).name).toBe("voice.wav");
    expect(formData.get("display_name")).toBe("Linus");
    expect(formData.get("person_id")).toBe("p-7");
  });
});

describe("api settings + preferences + identity", () => {
  it("getSettings + getTranscriptionOptions read the settings endpoints", async () => {
    await api.getSettings();
    await api.getTranscriptionOptions();
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/settings");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/settings/transcription-options");
  });

  it("updateSettings patches partial settings", async () => {
    await api.updateSettings({ summary_language: "ru" } as never);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/settings", {
      method: "PATCH",
      body: JSON.stringify({ summary_language: "ru" }),
    });
  });

  it("getPreferences + updatePreferences hit the preferences endpoint", async () => {
    await api.getPreferences();
    await api.updatePreferences({ theme: "dark", accent: "violet" });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/settings/preferences");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/settings/preferences", {
      method: "PATCH",
      body: JSON.stringify({ theme: "dark", accent: "violet" }),
    });
  });

  it("getIdentity + updateIdentity hit the identity endpoint", async () => {
    await api.getIdentity();
    await api.updateIdentity({ first_name: "Mik", last_name: null });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/settings/identity");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/settings/identity", {
      method: "PATCH",
      body: JSON.stringify({ first_name: "Mik", last_name: null }),
    });
  });

  it("voice-sharing read/enable/disable use POST and DELETE", async () => {
    await api.getVoiceSharing();
    await api.enableVoiceSharing();
    await api.disableVoiceSharing();
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/settings/voice-sharing");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/settings/voice-sharing", {
      method: "POST",
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/settings/voice-sharing", {
      method: "DELETE",
    });
  });
});

describe("api personalization terms + imports", () => {
  it("listPersonalizationTerms with a status filter builds the query string", async () => {
    await api.listPersonalizationTerms({ status: "pending" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms?status=pending");
  });

  it("listPersonalizationTerms without params omits the query string", async () => {
    await api.listPersonalizationTerms();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms");
  });

  it("createPersonalizationTerm defaults replacement + notes to null", async () => {
    await api.createPersonalizationTerm({ term: "WaiComputer" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms", {
      method: "POST",
      body: JSON.stringify({ term: "WaiComputer", replacement: null, notes: null }),
    });
  });

  it("createPersonalizationTerm forwards replacement + notes when present", async () => {
    await api.createPersonalizationTerm({
      term: "k8s",
      replacement: "Kubernetes",
      notes: "infra term",
    });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms", {
      method: "POST",
      body: JSON.stringify({ term: "k8s", replacement: "Kubernetes", notes: "infra term" }),
    });
  });

  it("updatePersonalizationTerm patches by id", async () => {
    await api.updatePersonalizationTerm("term-1", { status: "approved" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms/term-1", {
      method: "PATCH",
      body: JSON.stringify({ status: "approved" }),
    });
  });

  it("deletePersonalizationTerm issues a DELETE", async () => {
    await api.deletePersonalizationTerm("term-1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/personalization/terms/term-1", {
      method: "DELETE",
    });
  });

  it("importPersonalizationText uploads source_type=text", async () => {
    await api.importPersonalizationText("hello world");
    expect(mockedApiUpload).toHaveBeenCalledWith(
      "/api/personalization/imports",
      expect.any(FormData),
    );
    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect(formData.get("source_type")).toBe("text");
    expect(formData.get("text")).toBe("hello world");
  });

  it("importPersonalizationFile uploads source_type=file", async () => {
    const file = new File(["glossary"], "terms.txt", { type: "text/plain" });
    await api.importPersonalizationFile(file);
    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect(formData.get("source_type")).toBe("file");
    expect(formData.get("file")).toBeInstanceOf(File);
    expect((formData.get("file") as File).name).toBe("terms.txt");
  });
});

describe("api MCP connections + API keys", () => {
  it("listMcpConnections reads the connections endpoint", async () => {
    await api.listMcpConnections();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/mcp/oauth/connections");
  });

  it("revokeMcpConnection URL-encodes the client id", async () => {
    await api.revokeMcpConnection("client/with space");
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/mcp/oauth/connections/client%2Fwith%20space/revoke",
      { method: "POST" },
    );
  });

  it("listApiKeys reads the api-keys endpoint", async () => {
    await api.listApiKeys();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/api-keys");
  });

  it("createApiKey defaults expires_at to null and write off", async () => {
    await api.createApiKey("CI token");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: "CI token", expires_at: null, allow_memory_write: false }),
    });
  });

  it("createApiKey forwards an explicit expiry and memory-write opt-in", async () => {
    await api.createApiKey("CI token", {
      expiresAt: "2026-12-31T00:00:00Z",
      allowMemoryWrite: true,
    });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/api-keys", {
      method: "POST",
      body: JSON.stringify({
        name: "CI token",
        expires_at: "2026-12-31T00:00:00Z",
        allow_memory_write: true,
      }),
    });
  });

  it("revokeApiKey URL-encodes the id", async () => {
    await api.revokeApiKey("id/42");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/api-keys/id%2F42/revoke", {
      method: "POST",
    });
  });
});

describe("api dictation cleanup + entries", () => {
  it("cleanupDictation sends null vocabulary when none provided", async () => {
    await api.cleanupDictation("um hello");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/cleanup", {
      method: "POST",
      body: JSON.stringify({ text: "um hello", vocabulary: null }),
    });
  });

  it("cleanupDictation sends null vocabulary for an empty array", async () => {
    await api.cleanupDictation("um hello", []);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/cleanup", {
      method: "POST",
      body: JSON.stringify({ text: "um hello", vocabulary: null }),
    });
  });

  it("cleanupDictation forwards a non-empty vocabulary list", async () => {
    await api.cleanupDictation("k eights", ["k8s"]);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/cleanup", {
      method: "POST",
      body: JSON.stringify({ text: "k eights", vocabulary: ["k8s"] }),
    });
  });

  it("createDictationEntry forwards the entry payload verbatim", async () => {
    const input = {
      client_entry_id: "ce-1",
      raw_text: "raw",
      cleaned_text: "clean",
      duration_seconds: 3.5,
      word_count: 2,
      occurred_at: "2026-06-01T00:00:00Z",
    };
    await api.createDictationEntry(input);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/entries", {
      method: "POST",
      body: JSON.stringify(input),
    });
  });

  it("deleteDictationEntry URL-encodes the client entry id", async () => {
    await api.deleteDictationEntry("ce/9");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/entries/ce%2F9", {
      method: "DELETE",
    });
  });
});

describe("cryptoRandomUUID fallback (no crypto.randomUUID)", () => {
  it("createDictionaryWord generates an RFC4122 v4 id without crypto.randomUUID", async () => {
    const original = globalThis.crypto;
    try {
      // Force the non-crypto fallback path (api.ts L820-821).
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: undefined,
      });

      await api.createDictionaryWord({ word: "k8s", replacement: "Kubernetes" });

      const [, init] = mockedApiFetch.mock.calls[0]!;
      const body = JSON.parse(init?.body as string) as Record<string, unknown>;
      const id = body.client_word_id as string;
      expect(id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: original,
      });
    }
  });
});
