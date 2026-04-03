"use client";

import { useEffect, useState } from "react";
import {
  createAppItem,
  deleteApp,
  deleteAppItem,
  listAppItems,
  listAppDeployments,
  listApps,
  publishApp,
  rollbackApp,
} from "@/lib/api";
import { ApiError } from "@/lib/http";
import type { AppDeployment, AppItem, UserApp } from "@/lib/types";

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export function AppsView() {
  const [apps, setApps] = useState<UserApp[]>([]);
  const [selectedApp, setSelectedApp] = useState<UserApp | null>(null);
  const [items, setItems] = useState<AppItem[]>([]);
  const [deployments, setDeployments] = useState<AppDeployment[]>([]);
  const [error, setError] = useState<string | null>(null);

  function replaceApp(updatedApp: UserApp) {
    setApps((current) =>
      current.some((app) => app.id === updatedApp.id)
        ? current.map((app) => (app.id === updatedApp.id ? updatedApp : app))
        : [updatedApp, ...current],
    );
    if (selectedApp?.id === updatedApp.id) {
      setSelectedApp(updatedApp);
    }
  }

  async function loadApps() {
    try {
      const result = await listApps();
      setApps(result);
    } catch (err) {
      setError(formatError(err));
    }
  }

  useEffect(() => {
    let cancelled = false;
    listApps()
      .then((result) => {
        if (!cancelled) setApps(result);
      })
      .catch((err) => {
        if (!cancelled) setError(formatError(err));
      });
    return () => { cancelled = true; };
  }, []);

  async function loadSelectedAppData(appId: string) {
    const [appItems, appDeployments] = await Promise.all([
      listAppItems(appId),
      listAppDeployments(appId),
    ]);
    setItems(appItems);
    setDeployments(appDeployments);
  }

  async function handleSelectApp(app: UserApp) {
    setSelectedApp(app);
    setError(null);
    try {
      await loadSelectedAppData(app.id);
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleDeleteApp(appId: string) {
    setError(null);
    try {
      await deleteApp(appId);
      if (selectedApp?.id === appId) {
        setSelectedApp(null);
        setItems([]);
        setDeployments([]);
      }
      await loadApps();
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handlePublishApp(app: UserApp) {
    setError(null);
    try {
      const updated = await publishApp(app.id, {
        visibility: app.visibility,
        app_url: app.app_url ?? undefined,
      });
      replaceApp(updated);
      if (selectedApp?.id === updated.id) {
        setSelectedApp(updated);
        await loadSelectedAppData(updated.id);
      }
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleAddItem() {
    if (!selectedApp) return;
    setError(null);
    try {
      await createAppItem(selectedApp.id, { note: "New item", created: new Date().toISOString() });
      const result = await listAppItems(selectedApp.id);
      setItems(result);
      await loadApps();
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleRollbackDeployment(deploymentId: string) {
    if (!selectedApp) return;
    setError(null);
    try {
      const updated = await rollbackApp(selectedApp.id, {
        deployment_id: deploymentId,
        visibility: selectedApp.visibility,
      });
      replaceApp(updated);
      setSelectedApp(updated);
      await loadSelectedAppData(updated.id);
    } catch (err) {
      setError(formatError(err));
    }
  }

  async function handleDeleteItem(itemId: string) {
    if (!selectedApp) return;
    setError(null);
    try {
      await deleteAppItem(selectedApp.id, itemId);
      const result = await listAppItems(selectedApp.id);
      setItems(result);
      await loadApps();
    } catch (err) {
      setError(formatError(err));
    }
  }

  return (
    <div className="stack">
      {error && <p role="alert" style={{ color: "#cc0000", fontSize: "0.9rem" }}>{error}</p>}

      {/* App Grid */}
      {apps.length === 0 && !selectedApp ? (
        <section className="card" style={{ textAlign: "center", padding: "2rem", color: "var(--muted)" }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📱</div>
          <p>No apps yet. Ask Wai to create one:</p>
          <p style={{ fontSize: "0.9rem", marginTop: "0.5rem" }}>
            &quot;Create a habit tracker&quot; or &quot;Build an expense tracker&quot;
          </p>
        </section>
      ) : !selectedApp ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {apps.map((app) => (
            <button
              key={app.id}
              type="button"
              onClick={() => void handleSelectApp(app)}
              className="card"
              style={{
                textAlign: "center",
                cursor: "pointer",
                padding: "1.25rem 0.75rem",
                border: "1px solid var(--border)",
                background: "var(--card)",
              }}
            >
              <div style={{ fontSize: "1.5rem", marginBottom: "0.25rem" }}>
                {app.icon || "📦"}
              </div>
              <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{app.display_name}</div>
              <div style={{ color: "var(--muted)", fontSize: "0.78rem" }}>
                {app.status} · {app.visibility}
              </div>
              {app.description && (
                <div style={{ color: "var(--muted)", fontSize: "0.8rem", marginTop: "0.25rem" }}>
                  {app.description}
                </div>
              )}
              <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                {app.item_count} items
              </div>
            </button>
          ))}
        </div>
      ) : (
        /* App Detail View */
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
              <button type="button" onClick={() => setSelectedApp(null)}>
                ←
              </button>
              <h2 style={{ margin: 0 }}>
                {selectedApp.icon || "📦"} {selectedApp.display_name}
              </h2>
            </div>
            <div className="row" style={{ gap: "0.25rem" }}>
              <button type="button" onClick={() => void handleAddItem()}>
                + Add Item
              </button>
              <button type="button" onClick={() => void handlePublishApp(selectedApp)}>
                {selectedApp.status === "live" ? "Republish" : "Publish"}
              </button>
              {selectedApp.app_url && (
                <a
                  href={selectedApp.app_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    padding: "0.55rem 0.8rem",
                    borderRadius: "10px",
                    background: "var(--accent)",
                    color: "#fff",
                    textDecoration: "none",
                    fontSize: "0.9rem",
                  }}
                >
                  Open App ↗
                </a>
              )}
              <button
                type="button"
                onClick={() => void handleDeleteApp(selectedApp.id)}
                style={{ background: "#dc2626" }}
              >
                Delete
              </button>
            </div>
          </div>

          {items.length === 0 ? (
            <section className="card" style={{ textAlign: "center", padding: "1.5rem", color: "var(--muted)" }}>
              <p>No items yet. Add data through Wai chat or click &quot;+ Add Item&quot;.</p>
            </section>
          ) : (
            <div className="stack" style={{ gap: "0.5rem" }}>
              {items.map((item) => (
                <div
                  key={item.id}
                  className="card row"
                  style={{
                    justifyContent: "space-between",
                    padding: "0.75rem 1rem",
                  }}
                >
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      fontSize: "0.85rem",
                      margin: 0,
                      flex: 1,
                    }}
                  >
                    {JSON.stringify(item.data, null, 2)}
                  </pre>
                  <button
                    type="button"
                    onClick={() => void handleDeleteItem(item.id)}
                    style={{
                      background: "transparent",
                      color: "#dc2626",
                      border: "none",
                      cursor: "pointer",
                      padding: "0.25rem",
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          <section className="card" style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
            <div>
              Status: <strong>{selectedApp.status}</strong>
            </div>
            <div>
              Visibility: <strong>{selectedApp.visibility}</strong>
            </div>
            {selectedApp.published_at && (
              <div>Published: {new Date(selectedApp.published_at).toLocaleString()}</div>
            )}
            {selectedApp.last_used_at && (
              <div>Last used: {new Date(selectedApp.last_used_at).toLocaleString()}</div>
            )}
          </section>

          <section className="card" style={{ fontSize: "0.85rem" }}>
            <div style={{ marginBottom: "0.75rem", fontWeight: 600 }}>Deployments</div>
            {deployments.length === 0 ? (
              <div style={{ color: "var(--muted)" }}>No deployment history yet.</div>
            ) : (
              <div className="stack" style={{ gap: "0.75rem" }}>
                {deployments.map((deployment, index) => (
                  <article
                    key={deployment.id}
                    className="card"
                    style={{
                      padding: "0.85rem",
                      background: "var(--bg)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                      <div>
                        <div style={{ fontWeight: 600, marginBottom: "0.15rem" }}>
                          {deployment.deployment_mode === "production" ? "Live deployment" : "Preview deployment"}
                        </div>
                        <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                          {new Date(deployment.created_at).toLocaleString()} · {deployment.status} ·{" "}
                          {deployment.deployment_target}
                        </div>
                      </div>
                      {index > 0 && (
                        <button
                          type="button"
                          onClick={() => void handleRollbackDeployment(deployment.id)}
                        >
                          Roll back
                        </button>
                      )}
                    </div>

                    <div className="stack" style={{ gap: "0.35rem", marginTop: "0.75rem" }}>
                      <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                        Project: <strong>{deployment.cloudflare_project_name ?? "—"}</strong>
                      </div>
                      <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                        Bundle: <strong>{deployment.bundle_kind ?? "—"}</strong>
                      </div>
                      <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                        Framework: <strong>{deployment.framework ?? "—"}</strong>
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
                        {deployment.alias_url && (
                          <a href={deployment.alias_url} target="_blank" rel="noopener noreferrer">
                            Preview ↗
                          </a>
                        )}
                        {deployment.live_url && (
                          <a href={deployment.live_url} target="_blank" rel="noopener noreferrer">
                            Live ↗
                          </a>
                        )}
                        {deployment.deployment_url && (
                          <a href={deployment.deployment_url} target="_blank" rel="noopener noreferrer">
                            Deployment ↗
                          </a>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
