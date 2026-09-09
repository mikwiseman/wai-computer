// The upstream project tokens are public capabilities already shipped in the demos.
// Keep original students' records out of this separately published English edition.
const PROJECTS: Record<string, { token: string; collection: string }> = {
  hallownest: { token: "kdb-hallownest-cc75b4c3e5c3852fb2369e8923f1a49b", collection: "waitlist" },
  "block-modz": { token: "kdb-block-modz-d10c17a8810c454c4cdef0c82ea0fd1f", collection: "likes" },
  rifflegg: { token: "kdb-rifflegg-674176388267e09e54556ea1b124c1a7", collection: "matches" },
  bouquet: { token: "kdb-bouquet-0bc3c806b89e7ebc19df19f11d39dbe3", collection: "saved" },
  escape: { token: "kdb-escape-8ba12491c1cd99b7f3c3c93dda1728ac", collection: "games" },
};
const SITE = "wai.computer";
type Context = { params: Promise<{ project: string; collection: string }> };
function error(status: number) {
  return Response.json({ ok: false, error: status === 429 ? "Too many requests. Please try again later." : "Project data is unavailable. Please try again later." }, { status });
}
async function forward(request: Request, context: Context) {
  const { project, collection } = await context.params;
  const config = Object.hasOwn(PROJECTS, project) ? PROJECTS[project] : undefined;
  if (!config || config.collection !== collection) return error(404);
  const upstream = new URL(`https://wai.school/api/kdb/${config.token}/${collection}`);
  const query = new URL(request.url).searchParams;
  for (const name of ["limit", "order"]) if (query.has(name)) upstream.searchParams.set(name, query.get(name)!);
  let body: string | undefined;
  if (request.method === "POST") {
    const raw = await request.text();
    if (raw.length > 16_384) return error(413);
    try {
      const input = JSON.parse(raw);
      if (!input || typeof input.payload !== "object" || input.payload === null || Array.isArray(input.payload)) return error(400);
      body = JSON.stringify({ nick: input.nick, payload: { ...input.payload, site: SITE } });
    } catch { return error(400); }
  }
  try {
    const response = await fetch(upstream, { method: request.method, headers: { "Content-Type": "application/json" }, body, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!response.ok) return error(response.status);
    const data = await response.json();
    if (!data.ok) return error(502);
    if (request.method === "GET") {
      const items = Array.isArray(data.items) ? data.items.filter((item: { payload?: { site?: string } }) => item.payload?.site === SITE) : [];
      return Response.json({ ok: true, items }, { headers: { "Cache-Control": "no-store" } });
    }
    return Response.json({ ok: true, id: data.id });
  } catch { return error(502); }
}
export const GET = forward;
export const POST = forward;
