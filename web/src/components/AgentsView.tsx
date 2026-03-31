"use client";

import { useEffect, useState } from "react";
import { createAgent, deleteAgent, listAgents, runAgent } from "@/lib/api";
import { ApiError } from "@/lib/http";
import type { DigitalAgent } from "@/lib/types";

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export function AgentsView() {
  const [agents, setAgents] = useState<DigitalAgent[]>([]);
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    void loadAgents();
  }, []);

  async function loadAgents() {
    try {
      const result = await listAgents();
      setAgents(result);
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleCreate() {
    if (!description.trim() || creating) return;
    setCreating(true);
    setError(null);
    setSuccess(null);
    try {
      const agent = await createAgent(description);
      setDescription("");
      setSuccess(`Agent "${agent.name}" created!`);
      await loadAgents();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleRun(agentId: string) {
    setError(null);
    try {
      await runAgent(agentId);
      setSuccess("Agent triggered. Check back for results.");
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleDelete(agentId: string) {
    setError(null);
    try {
      await deleteAgent(agentId);
      await loadAgents();
    } catch (err) {
      setError(formatError(err));
    }
  }

  const statusIcon = (status: string) => {
    if (status === "active") return "🟢";
    if (status === "paused") return "⏸️";
    return "❌";
  };

  return (
    <div className="stack">
      <section className="card stack">
        <h2>Create Agent</h2>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
          Describe what you want the agent to do. Wai will figure out the schedule and tools.
        </p>
        <div className="row">
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Check HackerNews for AI news every morning..."
            disabled={creating}
            style={{ flex: 1 }}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
            }}
          />
          <button onClick={() => void handleCreate()} disabled={creating || !description.trim()}>
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      </section>

      {error && <p role="alert" style={{ color: "#cc0000", fontSize: "0.9rem" }}>{error}</p>}
      {success && <p role="status" style={{ fontSize: "0.9rem" }}>{success}</p>}

      {agents.length === 0 ? (
        <section className="card" style={{ textAlign: "center", padding: "2rem", color: "var(--muted)" }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🤖</div>
          <p>No agents yet. Create your first one above.</p>
        </section>
      ) : (
        <div className="stack">
          {agents.map((agent) => (
            <section key={agent.id} className="card stack" style={{ gap: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>
                    {statusIcon(agent.status)} {agent.name}
                  </strong>
                  <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                    {agent.cron_expression ?? "manual"} | {agent.run_count} runs
                    {agent.last_run_at
                      ? ` | Last: ${new Date(agent.last_run_at).toLocaleDateString()}`
                      : ""}
                  </div>
                </div>
                <div className="row" style={{ gap: "0.25rem" }}>
                  <button onClick={() => void handleRun(agent.id)}>Run</button>
                  <button onClick={() => void handleDelete(agent.id)} style={{ background: "#dc2626" }}>
                    Delete
                  </button>
                </div>
              </div>
              <p style={{ fontSize: "0.9rem", color: "var(--muted)" }}>{agent.description}</p>
              {agent.last_result && (
                <details>
                  <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>Last result</summary>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      fontSize: "0.8rem",
                      background: "var(--bg)",
                      padding: "0.5rem",
                      borderRadius: "6px",
                      marginTop: "0.25rem",
                    }}
                  >
                    {agent.last_result}
                  </pre>
                </details>
              )}
              {agent.last_error && (
                <p style={{ color: "#dc2626", fontSize: "0.8rem" }}>Error: {agent.last_error}</p>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
