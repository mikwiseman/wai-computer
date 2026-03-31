"use client";

import { useEffect, useState } from "react";
import {
  createAppItem,
  deleteApp,
  deleteAppItem,
  listAppItems,
  listApps,
} from "@/lib/api";
import { ApiError } from "@/lib/http";
import type { AppItem, UserApp } from "@/lib/types";

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export function AppsView() {
  const [apps, setApps] = useState<UserApp[]>([]);
  const [selectedApp, setSelectedApp] = useState<UserApp | null>(null);
  const [items, setItems] = useState<AppItem[]>([]);
  const [error, setError] = useState<string | null>(null);

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

  async function handleSelectApp(app: UserApp) {
    setSelectedApp(app);
    setError(null);
    try {
      const result = await listAppItems(app.id);
      setItems(result);
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
      }
      await loadApps();
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
        </div>
      )}
    </div>
  );
}
