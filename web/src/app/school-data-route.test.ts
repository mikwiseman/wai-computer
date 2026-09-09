import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./school-data/[project]/[collection]/route";
const context = { params: Promise.resolve({ project: "rifflegg", collection: "matches" }) };
afterEach(() => vi.unstubAllGlobals());
describe("English student records", () => {
  it("does not publish records from the original projects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ok: true, items: [
      { id: 1, nick: "Original", payload: {} },
      { id: 2, nick: "EnglishPlayer", payload: { site: "wai.computer" } },
    ] })));
    const response = await GET(new Request("https://wai.computer/school-data/rifflegg/matches?limit=50"), context);
    expect(await response.json()).toEqual({ ok: true, items: [{ id: 2, nick: "EnglishPlayer", payload: { site: "wai.computer" } }] });
  });
  it("marks all new records as belonging to the English website", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ok: true, id: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    const response = await POST(new Request("https://wai.computer/school-data/rifflegg/matches", { method: "POST", body: JSON.stringify({ nick: "Player", payload: { type: "create", site: "other" } }) }), context);
    expect(response.status).toBe(200);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ nick: "Player", payload: { type: "create", site: "wai.computer" } });
  });
  it("rejects unsupported collections without contacting the upstream", async () => {
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const response = await GET(new Request("https://wai.computer/school-data/rifflegg/players"), { params: Promise.resolve({ project: "rifflegg", collection: "players" }) });
    expect(response.status).toBe(404); expect(fetchMock).not.toHaveBeenCalled();
  });
  it("keeps errors in English", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: "upstream details" }, { status: 429 })));
    const response = await GET(new Request("https://wai.computer/school-data/rifflegg/matches"), context);
    expect(response.status).toBe(429); expect(await response.json()).toEqual({ ok: false, error: "Too many requests. Please try again later." });
  });
});
