"use client";

import { FormEvent, type Dispatch, type SetStateAction, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  runAdminSubscriptionRenewal,
  updateAdminPromoCode,
  updateAdminSubscription,
  updateAdminUserStatus,
  type AdminAuditLog,
  type AdminBillingSubscription,
  type AdminSubscriptionPatchInput,
  type AdminObservability,
  type AdminPromoCode,
  type AdminPromoRedemptionBucket,
  type AdminRevenueBucket,
  type AdminStats,
  type AdminUsageBucket,
  type AdminUserDetail,
  type AdminUserSummary,
} from "@/lib/admin";
import { logout } from "@/lib/api";

type AdminTab = "overview" | "promos" | "users" | "billing" | "observability" | "audit";
type PromoDraft = {
  note: string;
  duration_days: number | null;
  discount_percent: number | null;
  max_redemptions: number;
  expires_at: string; // yyyy-mm-dd; "" means no expiry
};

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

function defaultPromoExpiryDate(): string {
  const date = new Date();
  date.setDate(date.getDate() + 30);
  return date.toISOString().slice(0, 10);
}

function promoExpiryIso(dateValue: string): string | null {
  if (!dateValue) return null;
  return `${dateValue}T23:59:59.000Z`;
}

function isoToDateInput(value: string | null): string {
  return value ? value.slice(0, 10) : "";
}

// Subscription date inputs map to noon UTC so a chosen day is unambiguously
// in the past/future regardless of the viewer's timezone.
function dateInputToIso(dateValue: string): string | null {
  if (!dateValue) return null;
  return `${dateValue}T12:00:00.000Z`;
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
  const router = useRouter();
  const initialTab = (searchParams.get("tab") || "overview") as AdminTab;
  const [tab, setTab] = useState<AdminTab>(TABS.some((item) => item.id === initialTab) ? initialTab : "overview");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [promos, setPromos] = useState<AdminPromoCode[]>([]);
  const [promoDrafts, setPromoDrafts] = useState<Record<string, PromoDraft>>({});
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
    promotionType: "access" as "access" | "discount",
    durationDays: 30,
    discountPercent: 20,
    maxRedemptions: 1,
    expiresOn: defaultPromoExpiryDate(),
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
            discount_percent: promo.discount_percent,
            max_redemptions: promo.max_redemptions,
            expires_at: isoToDateInput(promo.expires_at),
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

  async function handleRunRenewal(subId: string) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await runAdminSubscriptionRenewal(subId, { reason: billingReason || null });
      await refreshAll();
      setMessage(
        result.charged
          ? "Renewal charged."
          : `Renewal skipped: ${result.reason ?? result.result ?? "not eligible"}.`,
      );
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Renewal failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setError(null);
    try {
      await logout();
      router.replace("/login");
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Logout failed.");
    }
  }

  async function handleCreatePromo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(async () => {
      const created = await createAdminPromoCode({
        code: newPromo.code.trim() || null,
        prefix: newPromo.prefix.trim() || "WAI",
        plan: "pro",
        promotion_type: newPromo.promotionType,
        billing_period: newPromo.period,
        duration_days: newPromo.promotionType === "access" ? newPromo.durationDays : null,
        discount_percent: newPromo.promotionType === "discount" ? newPromo.discountPercent : null,
        max_redemptions: newPromo.maxRedemptions,
        expires_at: promoExpiryIso(newPromo.expiresOn),
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
        <div className="admin-console__sidebar-footer">
          <button
            data-testid="admin-logout-button"
            type="button"
            className="ghost-button danger-button"
            onClick={handleLogout}
          >
            Logout
          </button>
        </div>
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
                <span>Auto prefix</span>
                <input value={newPromo.prefix} disabled={newPromo.code.trim().length > 0} onChange={(event) => setNewPromo((current) => ({ ...current, prefix: event.target.value }))} />
              </label>
              <label>
                <span>Type</span>
                <select value={newPromo.promotionType} onChange={(event) => setNewPromo((current) => ({ ...current, promotionType: event.target.value as "access" | "discount" }))}>
                  <option value="access">Pro access</option>
                  <option value="discount">Price discount</option>
                </select>
              </label>
              {newPromo.promotionType === "discount" ? (
                <label>
                  <span>Checkout period</span>
                  <select value={newPromo.period} onChange={(event) => setNewPromo((current) => ({ ...current, period: event.target.value as "month" | "year" }))}>
                    <option value="month">month</option>
                    <option value="year">year</option>
                  </select>
                </label>
              ) : null}
              <label>
                <span>{newPromo.promotionType === "access" ? "Pro days" : "Discount %"}</span>
                <input type="number" min={1} max={newPromo.promotionType === "discount" ? 100 : undefined} value={newPromo.promotionType === "access" ? newPromo.durationDays : newPromo.discountPercent} onChange={(event) => setNewPromo((current) => current.promotionType === "access" ? { ...current, durationDays: Number(event.target.value) } : { ...current, discountPercent: Number(event.target.value) })} />
              </label>
              <label>
                <span>Redemptions</span>
                <input type="number" min={1} value={newPromo.maxRedemptions} onChange={(event) => setNewPromo((current) => ({ ...current, maxRedemptions: Number(event.target.value) }))} />
              </label>
              <label>
                <span>Expires on</span>
                <input type="date" value={newPromo.expiresOn} onChange={(event) => setNewPromo((current) => ({ ...current, expiresOn: event.target.value }))} />
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
                  const promo = promos.find((item) => item.id === promoId);
                  if (!promo) return;
                  await updateAdminPromoCode(promoId, {
                    note: draft.note,
                    ...(promo.promotion_type === "access"
                      ? { duration_days: draft.duration_days }
                      : { discount_percent: draft.discount_percent }),
                    max_redemptions: draft.max_redemptions,
                    expires_at: promoExpiryIso(draft.expires_at),
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
                <BillingList subscriptions={selectedUserBilling} reason={billingReason} setReason={setBillingReason} busy={busy} runAction={runAction} onRunRenewal={handleRunRenewal} />
              </div>
            ) : null}
          </div>
        ) : null}

        {tab === "billing" ? (
          <div className="admin-section">
            <div className="admin-action-row admin-action-row--wide">
              <input value={billingReason} onChange={(event) => setBillingReason(event.target.value)} placeholder="billing reason" />
            </div>
            <BillingList subscriptions={billing} reason={billingReason} setReason={setBillingReason} busy={busy} runAction={runAction} onRunRenewal={handleRunRenewal} />
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
  drafts: Record<string, PromoDraft>;
  setDrafts: Dispatch<SetStateAction<Record<string, PromoDraft>>>;
  busy: boolean;
  onSave: (promoId: string) => Promise<void>;
  onToggle: (promo: AdminPromoCode) => Promise<void>;
  onArchive: (promo: AdminPromoCode) => Promise<void>;
}) {
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            <th>Created</th>
            <th>Code</th>
            <th>Type</th>
            <th>Status</th>
            <th>Use</th>
            <th>Pro days</th>
            <th>Discount %</th>
            <th>Period</th>
            <th>Expires</th>
            <th>Max</th>
            <th>Note</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {promos.map((promo) => {
            const draft = drafts[promo.id] ?? {
              note: "",
              duration_days: promo.duration_days,
              discount_percent: promo.discount_percent,
              max_redemptions: promo.max_redemptions,
              expires_at: isoToDateInput(promo.expires_at),
            };
            const code = promo.code ?? promo.normalized_code ?? "-";
            return (
              <tr key={promo.id}>
                <td>{fmtDate(promo.created_at)}</td>
                <td className="admin-code-cell">{code}</td>
                <td>{promo.promotion_type === "discount" ? "discount" : "access"}</td>
                <td>{promo.active ? "active" : "paused"}</td>
                <td>{promo.redeemed_count} / {promo.max_redemptions}</td>
                <td>
                  {promo.promotion_type === "access" ? (
                    <input type="number" min={1} value={draft.duration_days ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, duration_days: Number(event.target.value) } }))} />
                  ) : (
                    <span className="muted-text">—</span>
                  )}
                </td>
                <td>
                  {promo.promotion_type === "discount" ? (
                    <input type="number" min={1} max={100} value={draft.discount_percent ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, discount_percent: Number(event.target.value) } }))} />
                  ) : (
                    <span className="muted-text">—</span>
                  )}
                </td>
                <td>{promo.promotion_type === "discount" ? promo.billing_period : "-"}</td>
                <td>
                  <input type="date" value={draft.expires_at} onChange={(event) => setDrafts((current) => ({ ...current, [promo.id]: { ...draft, expires_at: event.target.value } }))} />
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
    </div>
  );
}

type SubEditDraft = {
  status: string;
  plan: string;
  billing_period: "month" | "year";
  current_period_start: string;
  current_period_end: string;
  trial_end: string;
  next_charge_at: string;
  cancel_at_period_end: boolean;
};

const SUB_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete", "expired"];

function subDraftFrom(sub: AdminBillingSubscription): SubEditDraft {
  return {
    status: sub.status,
    plan: sub.plan,
    billing_period: sub.billing_period === "year" ? "year" : "month",
    current_period_start: isoToDateInput(sub.current_period_start),
    current_period_end: isoToDateInput(sub.current_period_end),
    trial_end: isoToDateInput(sub.trial_end),
    next_charge_at: isoToDateInput(sub.tinkoff_next_charge_at),
    cancel_at_period_end: sub.cancel_at_period_end,
  };
}

// Build a PATCH body of ONLY the fields the admin actually changed, so e.g. an
// untouched status doesn't trigger a spurious cancel/resume call on Stripe.
function subPatchDiff(
  sub: AdminBillingSubscription,
  draft: SubEditDraft,
  reason: string,
): AdminSubscriptionPatchInput {
  const original = subDraftFrom(sub);
  const patch: AdminSubscriptionPatchInput = {};
  if (draft.status !== original.status) patch.status = draft.status;
  if (draft.plan !== original.plan) patch.plan = draft.plan;
  if (draft.billing_period !== original.billing_period) patch.billing_period = draft.billing_period;
  if (draft.cancel_at_period_end !== original.cancel_at_period_end)
    patch.cancel_at_period_end = draft.cancel_at_period_end;
  if (draft.current_period_start !== original.current_period_start)
    patch.current_period_start = dateInputToIso(draft.current_period_start);
  if (draft.current_period_end !== original.current_period_end)
    patch.current_period_end = dateInputToIso(draft.current_period_end);
  if (draft.trial_end !== original.trial_end) patch.trial_end = dateInputToIso(draft.trial_end);
  if (draft.next_charge_at !== original.next_charge_at)
    patch.next_charge_at = dateInputToIso(draft.next_charge_at);
  if (Object.keys(patch).length > 0) patch.reason = reason || null;
  return patch;
}

function BillingList({
  subscriptions,
  reason,
  busy,
  runAction,
  onRunRenewal,
}: {
  subscriptions: AdminBillingSubscription[];
  reason: string;
  setReason: (value: string) => void;
  busy: boolean;
  runAction: (action: () => Promise<void>, success: string) => Promise<void>;
  onRunRenewal: (id: string) => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<SubEditDraft | null>(null);
  return (
    <div className="admin-billing-list">
      {subscriptions.map((sub) => (
        <section key={sub.id} className="admin-billing-item">
          <div className="admin-billing-head">
            <div>
              <h3>{sub.user_email}</h3>
              <p>{sub.provider} · {sub.plan} · {sub.status} · {sub.cancel_at_period_end ? "cancel pending" : "renewing"}</p>
              <p className="muted-text">
                Period ends {fmtDate(sub.current_period_end)}
                {sub.provider === "tinkoff"
                  ? ` · next charge ${sub.cancel_at_period_end ? "—" : fmtDate(sub.tinkoff_next_charge_at)}`
                  : ""}
              </p>
            </div>
            <div className="admin-row-actions">
              <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => {
                if (editingId === sub.id) {
                  setEditingId(null);
                  setDraft(null);
                } else {
                  setEditingId(sub.id);
                  setDraft(subDraftFrom(sub));
                }
              }}>{editingId === sub.id ? "Close" : "Edit"}</button>
              {sub.provider === "tinkoff" ? (
                <button type="button" className="ghost-button compact-button" disabled={busy} onClick={() => onRunRenewal(sub.id)}>Run renewal now</button>
              ) : null}
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
          {editingId === sub.id && draft ? (
            <form className="admin-sub-edit" onSubmit={(event) => {
              event.preventDefault();
              const patch = subPatchDiff(sub, draft, reason);
              if (Object.keys(patch).length === 0) return;
              void runAction(async () => {
                await updateAdminSubscription(sub.id, patch);
                setEditingId(null);
                setDraft(null);
              }, "Subscription updated.");
            }}>
              <label>
                <span>Status</span>
                <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
                  {SUB_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label>
                <span>Plan</span>
                <select value={draft.plan} onChange={(event) => setDraft({ ...draft, plan: event.target.value })}>
                  <option value="pro">pro</option>
                  <option value="free">free</option>
                </select>
              </label>
              <label>
                <span>Billing period</span>
                <select value={draft.billing_period} onChange={(event) => setDraft({ ...draft, billing_period: event.target.value as "month" | "year" })}>
                  <option value="month">month</option>
                  <option value="year">year</option>
                </select>
              </label>
              <label>
                <span>Period start</span>
                <input type="date" value={draft.current_period_start} onChange={(event) => setDraft({ ...draft, current_period_start: event.target.value })} />
              </label>
              <label>
                <span>Period end</span>
                <input type="date" value={draft.current_period_end} onChange={(event) => setDraft({ ...draft, current_period_end: event.target.value })} />
              </label>
              <label>
                <span>Trial end</span>
                <input type="date" value={draft.trial_end} onChange={(event) => setDraft({ ...draft, trial_end: event.target.value })} />
              </label>
              <label>
                <span>{sub.provider === "stripe" ? "Next charge (synced to Stripe)" : "Next charge"}</span>
                <input type="date" value={draft.next_charge_at} onChange={(event) => setDraft({ ...draft, next_charge_at: event.target.value })} />
              </label>
              <label className="admin-checkbox">
                <input type="checkbox" checked={draft.cancel_at_period_end} onChange={(event) => setDraft({ ...draft, cancel_at_period_end: event.target.checked })} />
                <span>Cancel at period end</span>
              </label>
              {sub.provider === "stripe" ? (
                <p className="muted-text admin-form-wide">Date, status and cancel edits are sent to Stripe; plan and period changes must be made in Stripe.</p>
              ) : null}
              <button type="submit" disabled={busy}>Save subscription</button>
            </form>
          ) : null}
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
