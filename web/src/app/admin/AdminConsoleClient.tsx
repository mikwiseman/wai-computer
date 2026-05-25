"use client";

import { FormEvent, type Dispatch, type SetStateAction, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  archiveAdminPromoCode,
  cancelAdminSubscription,
  createAdminPromoCode,
  getAdminObservability,
  getAdminStats,
  getAdminUser,
  grantAdminSubscription,
  listAdminAudit,
  listAdminBilling,
  listAdminPromoCodes,
  listAdminUsers,
  refundAdminInvoice,
  resumeAdminSubscription,
  updateAdminPromoCode,
  updateAdminUserStatus,
  type AdminAuditLog,
  type AdminBillingSubscription,
  type AdminObservability,
  type AdminPromoCode,
  type AdminPromoRedemptionBucket,
  type AdminRevenueBucket,
  type AdminStats,
  type AdminUsageBucket,
  type AdminUserDetail,
  type AdminUserSummary,
} from "@/lib/admin";

type AdminTab = "overview" | "promos" | "users" | "billing" | "observability" | "audit";

const TABS: Array<{ id: AdminTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "promos", label: "Promo codes" },
  { id: "users", label: "Users" },
  { id: "billing", label: "Billing" },
  { id: "observability", label: "Observability" },
  { id: "audit", label: "Audit" },
];

function fmtNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function fmtDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function metricEntries(record: Record<string, number>): Array<[string, number]> {
  return Object.entries(record).sort(([a], [b]) => a.localeCompare(b));
}

function promoMetricRows(stats: AdminStats["promo"]): Array<[string, number]> {
  return [
    ["total", stats.total],
    ["active", stats.active],
    ["paused", stats.paused],
    ["archived", stats.archived],
    ["expired", stats.expired],
    ["exhausted", stats.exhausted],
    ["redemptions", stats.redemptions],
  ];
}

export function AdminConsoleClient() {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") || "overview") as AdminTab;
  const [tab, setTab] = useState<AdminTab>(TABS.some((item) => item.id === initialTab) ? initialTab : "overview");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [promos, setPromos] = useState<AdminPromoCode[]>([]);
  const [promoDrafts, setPromoDrafts] = useState<Record<string, { note: string; duration_days: number; max_redemptions: number }>>({});
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [selectedUser, setSelectedUser] = useState<AdminUserDetail | null>(null);
  const [billing, setBilling] = useState<AdminBillingSubscription[]>([]);
  const [observability, setObservability] = useState<AdminObservability | null>(null);
  const [audit, setAudit] = useState<AdminAuditLog[]>([]);
  const [userQuery, setUserQuery] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newPromo, setNewPromo] = useState({
    code: "",
    prefix: "WAI",
    durationDays: 30,
    maxRedemptions: 1,
    expiresDays: 30,
    period: "month" as "month" | "year",
    note: "",
  });
  const [latestPlaintextCode, setLatestPlaintextCode] = useState<string | null>(null);
  const [userAction, setUserAction] = useState({
    status: "paused" as AdminUserSummary["account_status"],
    reason: "",
    grantDays: 30,
  });
  const [billingReason, setBillingReason] = useState("");

  async function refreshAll() {
    setError(null);
    const [freshStats, freshPromos, freshUsers, freshBilling, freshObservability, freshAudit] =
      await Promise.all([
        getAdminStats(),
        listAdminPromoCodes(),
        listAdminUsers(userQuery),
        listAdminBilling(),
        getAdminObservability(),
        listAdminAudit(),
      ]);
    setStats(freshStats);
    setPromos(freshPromos);
    setPromoDrafts(
      Object.fromEntries(
        freshPromos.map((promo) => [
          promo.id,
          {
            note: promo.note ?? "",
            duration_days: promo.duration_days,
            max_redemptions: promo.max_redemptions,
          },
        ]),
      ),
    );
    setUsers(freshUsers);
    setBilling(freshBilling);
    setObservability(freshObservability);
    setAudit(freshAudit);
  }

  useEffect(() => {
    setBusy(true);
    refreshAll()
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Admin data failed to load."))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedUserBilling = useMemo(() => {
    if (!selectedUser) return [];
    return billing.filter((item) => item.user_id === selectedUser.id);
  }, [billing, selectedUser]);

  async function runAction(action: () => Promise<void>, success: string) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await action();
      await refreshAll();
      setMessage(success);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Admin action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePromo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(async () => {
      const created = await createAdminPromoCode({
        code: newPromo.code.trim() || null,
        prefix: newPromo.prefix.trim() || "WAI",
        plan: "pro",
        billing_period: newPromo.period,
        duration_days: newPromo.durationDays,
        max_redemptions: newPromo.maxRedemptions,
        expires_days: newPromo.expiresDays,
        note: newPromo.note.trim() || null,
      });
      setLatestPlaintextCode(created.code ?? null);
      setNewPromo((current) => ({ ...current, code: "", note: "" }));
    }, "Promo code created.");
  }

  async function searchUsers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(async () => {
      setUsers(await listAdminUsers(userQuery));
      setSelectedUser(null);
    }, "Users loaded.");
  }

  async function openUser(userId: string) {
    setBusy(true);
    setError(null);
    try {
      const detail = await getAdminUser(userId);
      setSelectedUser(detail);
      setUserAction((current) => ({
        ...current,
        status: detail.account_status === "active" ? "paused" : "active",
      }));
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "User failed to load.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="admin-console">
      <aside className="admin-console__sidebar" aria-label="Admin navigation">
        <div>
          <p className="admin-kicker">WaiComputer</p>
          <h1>Admin</h1>
        </div>
        <nav className="admin-tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "is-active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      <section className="admin-console__main">
        <div className="admin-toolbar">
          <div>
            <p className="admin-kicker">{TABS.find((item) => item.id === tab)?.label}</p>
            <h2>{tab === "overview" ? "Statistics" : TABS.find((item) => item.id === tab)?.label}</h2>
          </div>
          <button type="button" className="ghost-button" onClick={() => void runAction(refreshAll, "Admin data refreshed.")} disabled={busy}>
            Refresh
          </button>
        </div>

        {message ? <p className="inline-success">{message}</p> : null}
        {error ? <p className="inline-alert">{error}</p> : null}
        {busy ? <p className="muted-text">Loading...</p> : null}

        {tab === "overview" && stats ? (
          <div className="admin-section">
            <div className="admin-metrics">
              <div>
                <span>Total users</span>
                <strong>{fmtNumber(stats.users.total)}</strong>
              </div>
              <div>
                <span>New users 30d</span>
                <strong>{fmtNumber(stats.users.new_30d)}</strong>
              </div>
              <div>
                <span>Total words</span>
                <strong>{fmtNumber(stats.usage.total_words)}</strong>
              </div>
              <div>
                <span>Recordings</span>
                <strong>{fmtNumber(stats.usage.recording_count)}</strong>
              </div>
            </div>
            <div className="admin-grid">
              <MetricTable title="Users by status" rows={metricEntries(stats.users.by_status)} />
              <MetricTable title="Subscriptions by provider" rows={metricEntries(stats.billing.subscriptions_by_provider)} />
              <MetricTable title="Subscriptions by status" rows={metricEntries(stats.billing.subscriptions_by_status)} />
              <MetricTable title="Promo codes" rows={promoMetricRows(stats.promo)} />
              <MetricTable title="Revenue" rows={metricEntries(stats.billing.revenue_by_currency)} />
              <MetricTable
                title="Usage"
                rows={[
                  ["recording_words", stats.usage.recording_words],
                  ["dictation_words", stats.usage.dictation_words],
                  ["failed_recordings", stats.usage.failed_recordings],
                ]}
              />
              <UsageBucketTable title="Monthly usage" rows={stats.usage.monthly.slice(-12)} />
              <UsageBucketTable title="Yearly usage" rows={stats.usage.yearly} />
              <RevenueBucketTable title="Monthly revenue" rows={stats.billing.monthly_revenue.slice(-12)} />
              <PromoRedemptionBucketTable title="Promo redemptions" rows={stats.promo.monthly_redemptions.slice(-12)} />
            </div>
          </div>
        ) : null}

        {tab === "promos" ? (
          <div className="admin-section">
            <form className="admin-inline-form" onSubmit={handleCreatePromo}>
              <label>
                <span>Code</span>
                <input value={newPromo.code} onChange={(event) => setNewPromo((current) => ({ ...current, code: event.target.value }))} placeholder="auto" />
              </label>
              <label>
                <span>Prefix</span>
                <input value={newPromo.prefix} onChange={(event) => setNewPromo((current) => ({ ...current, prefix: event.target.value }))} />
              </label>
              <label>
                <span>Period</span>
                <select value={newPromo.period} onChange={(event) => setNewPromo((current) => ({ ...current, period: event.target.value as "month" | "year" }))}>
                  <option value="month">month</option>
                  <option value="year">year</option>
                </select>
              </label>
              <label>
                <span>Pro days</span>
                <input type="number" min={1} value={newPromo.durationDays} onChange={(event) => setNewPromo((current) => ({ ...current, durationDays: Number(event.target.value) }))} />
              </label>
              <label>
                <span>Redemptions</span>
                <input type="number" min={1} value={newPromo.maxRedemptions} onChange={(event) => setNewPromo((current) => ({ ...current, maxRedemptions: Number(event.target.value) }))} />
              </label>
              <label>
                <span>Expires days</span>
                <input type="number" min={1} value={newPromo.expiresDays} onChange={(event) => setNewPromo((current) => ({ ...current, expiresDays: Number(event.target.value) }))} />
              </label>
              <label className="admin-form-wide">
                <span>Note</span>
                <input value={newPromo.note} onChange={(event) => setNewPromo((current) => ({ ...current, note: event.target.value }))} />
              </label>
              <button type="submit" disabled={busy}>Create</button>
            </form>
            {latestPlaintextCode ? (
              <div className="admin-once">
                <span>Plaintext promo code</span>
                <strong>{latestPlaintextCode}</strong>
              </div>
            ) : null}
            <PromoTable
              promos={promos}
              drafts={promoDrafts}
              setDrafts={setPromoDrafts}
              busy={busy}
              onSave={(promoId) =>
                runAction(async () => {
                  const draft = promoDrafts[promoId];
                  await updateAdminPromoCode(promoId, {
                    note: draft.note,
                    duration_days: draft.duration_days,
                    max_redemptions: draft.max_redemptions,
                  });
                }, "Promo code updated.")
              }
              onToggle={(promo) =>
                runAction(async () => {
                  await updateAdminPromoCode(promo.id, { active: !promo.active });
                }, promo.active ? "Promo code paused." : "Promo code resumed.")
              }
              onArchive={(promo) =>
                runAction(async () => {
                  await archiveAdminPromoCode(promo.id);
                }, "Promo code archived.")
              }
            />
          </div>
        ) : null}

        {tab === "users" ? (
          <div className="admin-section admin-users-layout">
            <div>
              <form className="admin-search" onSubmit={searchUsers}>
                <input value={userQuery} onChange={(event) => setUserQuery(event.target.value)} placeholder="email or id" />
                <button type="submit" disabled={busy}>Search</button>
              </form>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Plan</th>
                    <th>Words</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} onClick={() => void openUser(user.id)}>
                      <td>{user.email}</td>
                      <td>{user.account_status}</td>
                      <td>{user.current_plan}</td>
                      <td>{fmtNumber(user.dictation_words + user.recording_words)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selectedUser ? (
              <div className="admin-detail-panel">
                <h3>{selectedUser.email}</h3>
                <dl className="admin-detail-list">
                  <div><dt>Status</dt><dd>{selectedUser.account_status}</dd></div>
                  <div><dt>Plan</dt><dd>{selectedUser.current_plan}</dd></div>
                  <div><dt>Recordings</dt><dd>{fmtNumber(selectedUser.recording_count)}</dd></div>
                  <div><dt>Words</dt><dd>{fmtNumber(selectedUser.dictation_words + selectedUser.recording_words)}</dd></div>
                </dl>
                <div className="admin-action-row">
                  <select value={userAction.status} onChange={(event) => setUserAction((current) => ({ ...current, status: event.target.value as AdminUserSummary["account_status"] }))}>
                    <option value="active">active</option>
                    <option value="paused">paused</option>
                    <option value="deactivated">deactivated</option>
                  </select>
                  <input value={userAction.reason} onChange={(event) => setUserAction((current) => ({ ...current, reason: event.target.value }))} placeholder="reason" />
                  <button type="button" disabled={busy} onClick={() => void runAction(async () => {
                    await updateAdminUserStatus(selectedUser.id, { status: userAction.status, reason: userAction.reason || null });
                    setSelectedUser(await getAdminUser(selectedUser.id));
                  }, "User status updated.")}>Apply</button>
                </div>
                <div className="admin-action-row">
                  <input type="number" min={1} value={userAction.grantDays} onChange={(event) => setUserAction((current) => ({ ...current, grantDays: Number(event.target.value) }))} />
                  <button type="button" disabled={busy} onClick={() => void runAction(async () => {
                    await grantAdminSubscription(selectedUser.id, { duration_days: userAction.grantDays, reason: userAction.reason || null });
                    setSelectedUser(await getAdminUser(selectedUser.id));
                  }, "Admin Pro granted.")}>Grant Pro</button>
                </div>
                <BillingList subscriptions={selectedUserBilling} reason={billingReason} setReason={setBillingReason} busy={busy} runAction={runAction} />
              </div>
            ) : null}
          </div>
        ) : null}

        {tab === "billing" ? (
          <div className="admin-section">
            <div className="admin-action-row admin-action-row--wide">
              <input value={billingReason} onChange={(event) => setBillingReason(event.target.value)} placeholder="billing reason" />
            </div>
            <BillingList subscriptions={billing} reason={billingReason} setReason={setBillingReason} busy={busy} runAction={runAction} />
          </div>
        ) : null}

        {tab === "observability" && observability ? (
          <div className="admin-section">
            <div className="admin-grid">
              <MetricTable
                title="Server"
                rows={[
                  ["database_connected", observability.server.database === "connected" ? 1 : 0],
                  ["sentry_configured", observability.sentry.configured ? 1 : 0],
                ]}
              />
              <MetricTable
                title="Recording pipeline"
                rows={[
                  ["failed_rate_24h", Math.round(observability.recording_pipeline.failed_rate_24h * 100)],
                  ["stuck_processing", observability.recording_pipeline.stuck_processing_count],
                  [
                    "low_coverage_24h",
                    observability.recording_pipeline.low_transcript_coverage_count_24h,
                  ],
                ]}
              />
              <MetricTable
                title="Status counts"
                rows={metricEntries(observability.recording_pipeline.status_counts)}
              />
              <section className="admin-metric-table">
                <h3>Sentry</h3>
                <dl>
                  <div>
                    <dt>Status</dt>
                    <dd>{observability.sentry.configured ? "configured" : "not configured"}</dd>
                  </div>
                  <div>
                    <dt>Environment</dt>
                    <dd>{observability.sentry.environment ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>Release</dt>
                    <dd>{observability.sentry.release ?? observability.server.release ?? "-"}</dd>
                  </div>
                </dl>
              </section>
              <section className="admin-metric-table">
                <h3>Alerts</h3>
                <table className="admin-mini-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Title</th>
                      <th>Code</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {observability.alerts.map((item) => (
                      <tr key={item.code}>
                        <td>{item.severity}</td>
                        <td>{item.title}</td>
                        <td>{item.code}</td>
                        <td>{item.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          </div>
        ) : null}

        {tab === "audit" ? (
          <div className="admin-section">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((item) => (
                  <tr key={item.id}>
                    <td>{fmtDate(item.created_at)}</td>
                    <td>{item.action}</td>
                    <td>{item.target_type}:{item.target_id}</td>
                    <td>{item.reason ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function MetricTable({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  return (
    <section className="admin-metric-table">
      <h3>{title}</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label.replaceAll("_", " ")}</dt>
            <dd>{fmtNumber(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function UsageBucketTable({ title, rows }: { title: string; rows: AdminUsageBucket[] }) {
  return (
    <section className="admin-metric-table">
      <h3>{title}</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Words</th>
            <th>Recordings</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.period}>
              <td>{row.period}</td>
              <td>{fmtNumber(row.total_words)}</td>
              <td>{fmtNumber(row.recording_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RevenueBucketTable({ title, rows }: { title: string; rows: AdminRevenueBucket[] }) {
  return (
    <section className="admin-metric-table">
      <h3>{title}</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Currency</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.period}-${row.currency}`}>
              <td>{row.period}</td>
              <td>{row.currency}</td>
              <td>{fmtNumber(row.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PromoRedemptionBucketTable({
  title,
  rows,
}: {
  title: string;
  rows: AdminPromoRedemptionBucket[];
}) {
  return (
    <section className="admin-metric-table">
      <h3>{title}</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Redemptions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.period}>
              <td>{row.period}</td>
              <td>{fmtNumber(row.redemptions)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PromoTable({
  promos,
  drafts,
  setDrafts,
  busy,
  onSave,
  onToggle,
  onArchive,
}: {
  promos: AdminPromoCode[];
  drafts: Record<string, { note: string; duration_days: number; max_redemptions: number }>;
  setDrafts: Dispatch<
    SetStateAction<
      Record<string, { note: string; duration_days: number; max_redemptions: number }>
    >
  >;
  busy: boolean;
  onSave: (promoId: string) => Promise<void>;
  onToggle: (promo: AdminPromoCode) => Promise<void>;
  onArchive: (promo: AdminPromoCode) => Promise<void>;
}) {
  return (
    <table className="admin-table">
      <thead>
        <tr>
          <th>Created</th>
          <th>Status</th>
          <th>Plan</th>
          <th>Use</th>
          <th>Days</th>
          <th>Max</th>
          <th>Note</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {promos.map((promo) => {
          const draft = drafts[promo.id] ?? { note: "", duration_days: promo.duration_days, max_redemptions: promo.max_redemptions };
          return (
            <tr key={promo.id}>
              <td>{fmtDate(promo.created_at)}</td>
              <td>{promo.active ? "active" : "paused"}</td>
              <td>{promo.plan}</td>
              <td>{promo.redeemed_count} / {promo.max_redemptions}</td>
              <td>
                <input type="number" min={1} value={draft.duration_days} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, duration_days: Number(event.target.value) } }))} />
              </td>
              <td>
                <input type="number" min={promo.redeemed_count || 1} value={draft.max_redemptions} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, max_redemptions: Number(event.target.value) } }))} />
              </td>
              <td>
                <input value={draft.note} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, note: event.target.value } }))} />
              </td>
              <td className="admin-row-actions">
                <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => void onSave(promo.id)}>Save</button>
                <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => void onToggle(promo)}>{promo.active ? "Pause" : "Resume"}</button>
                <button type="button" className="ghost-button compact-button danger-button" disabled={busy} onClick={() => void onArchive(promo)}>Archive</button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function BillingList({
  subscriptions,
  reason,
  busy,
  runAction,
}: {
  subscriptions: AdminBillingSubscription[];
  reason: string;
  setReason: (value: string) => void;
  busy: boolean;
  runAction: (action: () => Promise<void>, success: string) => Promise<void>;
}) {
  return (
    <div className="admin-billing-list">
      {subscriptions.map((sub) => (
        <section key={sub.id} className="admin-billing-item">
          <div className="admin-billing-head">
            <div>
              <h3>{sub.user_email}</h3>
              <p>{sub.provider} · {sub.plan} · {sub.status} · {sub.cancel_at_period_end ? "cancel pending" : "renewing"}</p>
            </div>
            <div className="admin-row-actions">
              <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => void runAction(async () => {
                await cancelAdminSubscription(sub.id, { mode: "period_end", reason: reason || null });
              }, "Subscription cancellation scheduled.")}>Cancel later</button>
              <button type="button" className="ghost-button compact-button danger-button" disabled={busy} onClick={() => void runAction(async () => {
                await cancelAdminSubscription(sub.id, { mode: "immediate", reason: reason || null });
              }, "Subscription canceled.")}>Cancel now</button>
              <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => void runAction(async () => {
                await resumeAdminSubscription(sub.id, { reason: reason || null });
              }, "Subscription resumed.")}>Resume</button>
            </div>
          </div>
          {sub.invoices.length ? (
            <table className="admin-table admin-table--compact">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Paid</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {sub.invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td>{invoice.provider_payment_id ?? invoice.id.slice(0, 8)}</td>
                    <td>{invoice.amount} {invoice.currency}</td>
                    <td>{invoice.status}</td>
                    <td>{fmtDate(invoice.paid_at)}</td>
                    <td>
                      <button type="button" className="ghost-button compact-button danger-button" disabled={busy || invoice.status !== "paid"} onClick={() => void runAction(async () => {
                        await refundAdminInvoice(invoice.id, { amount_minor: null, reason: reason || "requested_by_customer" });
                      }, "Invoice refunded.")}>Refund</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      ))}
    </div>
  );
}
