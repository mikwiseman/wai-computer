"use client";

import {
  FormEvent,
  type CSSProperties,
  type Dispatch,
  type SetStateAction,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  archiveAdminPromoCode,
  cancelAdminSubscription,
  createAdminPromoCode,
  getAdminAiUsage,
  getAdminDeepgramUsage,
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
  type AdminAiUsage,
  type AdminAiUsageFilters,
  type AdminBillingSubscription,
  type AdminDeepgramUsage,
  type AdminDeepgramUsageFilters,
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

type AdminTab =
  | "overview"
  | "promos"
  | "users"
  | "billing"
  | "ai-usage"
  | "deepgram"
  | "observability"
  | "audit";
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
  { id: "ai-usage", label: "AI usage" },
  { id: "deepgram", label: "Deepgram" },
  { id: "observability", label: "Observability" },
  { id: "audit", label: "Audit" },
];

function fmtNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function fmtHours(valueSeconds: number): string {
  return `${(valueSeconds / 3600).toLocaleString("en-US", {
    maximumFractionDigits: 1,
  })} h`;
}

function fmtMinutes(valueSeconds: number | null | undefined): string {
  const value = valueSeconds ?? 0;
  return `${(value / 60).toLocaleString("en-US", {
    maximumFractionDigits: 1,
  })} min`;
}

function fmtUsd(value: number | null | undefined): string {
  return `$${(value ?? 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

function fmtLatency(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value.toLocaleString("en-US")} ms`;
}

function fmtMoneyByCurrency(value: Record<string, number>): string {
  const entries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return "-";
  return entries
    .map(([currency, amount]) => `${currency} ${amount.toLocaleString("en-US")}`)
    .join(", ");
}

function fmtDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtDateTime(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
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

const DEFAULT_AI_USAGE_FILTERS: Required<
  Pick<AdminAiUsageFilters, "days" | "provider" | "feature" | "model" | "status" | "q" | "limit">
> = {
  days: 7,
  provider: "",
  feature: "",
  model: "",
  status: "",
  q: "",
  limit: 100,
};

const DEFAULT_DEEPGRAM_USAGE_FILTERS: Required<Pick<AdminDeepgramUsageFilters, "days" | "limit">> = {
  days: 7,
  limit: 100,
};

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
  const [aiUsage, setAiUsage] = useState<AdminAiUsage | null>(null);
  const [aiUsageFilters, setAiUsageFilters] = useState(DEFAULT_AI_USAGE_FILTERS);
  const [deepgramUsage, setDeepgramUsage] = useState<AdminDeepgramUsage | null>(null);
  const [deepgramUsageFilters, setDeepgramUsageFilters] = useState(
    DEFAULT_DEEPGRAM_USAGE_FILTERS,
  );
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
    const [
      freshStats,
      freshPromos,
      freshUsers,
      freshBilling,
      freshAiUsage,
      freshDeepgramUsage,
      freshObservability,
      freshAudit,
    ] =
      await Promise.all([
        getAdminStats(),
        listAdminPromoCodes(),
        listAdminUsers(userQuery),
        listAdminBilling(),
        getAdminAiUsage(aiUsageFilters),
        getAdminDeepgramUsage(deepgramUsageFilters),
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
    setAiUsage(freshAiUsage);
    setDeepgramUsage(freshDeepgramUsage);
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
      if (result.charged) {
        setMessage("Renewal charged.");
      } else if (result.skipped) {
        // No charge was attempted — a gate (e.g. cancellation pending) stopped it.
        setMessage(`Renewal skipped: ${result.reason ?? "not eligible"}.`);
      } else {
        // The charge was attempted and the provider rejected it (e.g. Tinkoff
        // ErrorCode 10 on the DEMO terminal); the subscription is now past_due.
        setError(`Renewal attempt failed at the provider (status: ${result.status ?? "unknown"}).`);
      }
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

  async function applyAiUsageFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      setAiUsage(await getAdminAiUsage(aiUsageFilters));
      setMessage("AI usage loaded.");
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "AI usage failed to load.");
    } finally {
      setBusy(false);
    }
  }

  async function applyDeepgramUsageFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      setDeepgramUsage(await getAdminDeepgramUsage(deepgramUsageFilters));
      setMessage("Deepgram usage loaded.");
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Deepgram usage failed to load.");
    } finally {
      setBusy(false);
    }
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
                    <th>Hours</th>
                    <th>AI tokens</th>
                    <th>Money</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} onClick={() => void openUser(user.id)}>
                      <td>{user.email}</td>
                      <td>{user.account_status}</td>
                      <td>{user.current_plan}</td>
                      <td>{fmtNumber(user.dictation_words + user.recording_words)}</td>
                      <td>{fmtHours(user.transcription_duration_seconds)}</td>
                      <td>{fmtNumber(user.companion_total_tokens)}</td>
                      <td>{fmtMoneyByCurrency(user.revenue_by_currency)}</td>
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
                  <div><dt>Recording hours</dt><dd>{fmtHours(selectedUser.recording_duration_seconds)}</dd></div>
                  <div><dt>Dictation hours</dt><dd>{fmtHours(selectedUser.dictation_duration_seconds)}</dd></div>
                  <div><dt>AI tokens</dt><dd>{fmtNumber(selectedUser.companion_total_tokens)}</dd></div>
                  <div><dt>Cached tokens</dt><dd>{fmtNumber(selectedUser.companion_cached_tokens)}</dd></div>
                  <div><dt>Money</dt><dd>{fmtMoneyByCurrency(selectedUser.revenue_by_currency)}</dd></div>
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

        {tab === "ai-usage" && aiUsage ? (
          <div className="admin-section">
            <form className="admin-inline-form" onSubmit={applyAiUsageFilters}>
              <label>
                <span>Window</span>
                <select
                  value={aiUsageFilters.days}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      days: Number(event.target.value),
                    }))
                  }
                >
                  <option value={1}>1d</option>
                  <option value={7}>7d</option>
                  <option value={30}>30d</option>
                  <option value={90}>90d</option>
                </select>
              </label>
              <label>
                <span>Provider</span>
                <input
                  value={aiUsageFilters.provider}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      provider: event.target.value,
                    }))
                  }
                  placeholder="openai, deepgram"
                />
              </label>
              <label>
                <span>Feature</span>
                <input
                  value={aiUsageFilters.feature}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      feature: event.target.value,
                    }))
                  }
                  placeholder="companion, recording"
                />
              </label>
              <label>
                <span>Model</span>
                <input
                  value={aiUsageFilters.model}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      model: event.target.value,
                    }))
                  }
                  placeholder="gpt-5.5"
                />
              </label>
              <label>
                <span>Status</span>
                <select
                  value={aiUsageFilters.status}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      status: event.target.value,
                    }))
                  }
                >
                  <option value="">all</option>
                  <option value="succeeded">succeeded</option>
                  <option value="failed">failed</option>
                  <option value="refused">refused</option>
                </select>
              </label>
              <label>
                <span>User</span>
                <input
                  value={aiUsageFilters.q}
                  onChange={(event) =>
                    setAiUsageFilters((current) => ({
                      ...current,
                      q: event.target.value,
                    }))
                  }
                  placeholder="email or id"
                />
              </label>
              <button type="submit" disabled={busy}>Apply</button>
            </form>
            <div className="admin-metrics">
              <div>
                <span>Estimated cost</span>
                <strong>{fmtUsd(aiUsage.summary.estimated_cost_usd)}</strong>
              </div>
              <div>
                <span>Total tokens</span>
                <strong>{fmtNumber(aiUsage.summary.total_tokens)}</strong>
              </div>
              <div>
                <span>Billable audio</span>
                <strong>{fmtMinutes(aiUsage.summary.billable_seconds)}</strong>
              </div>
              <div>
                <span>Failed/refused</span>
                <strong>{fmtNumber(aiUsage.summary.failed_events + aiUsage.summary.refused_events)}</strong>
              </div>
            </div>
            <div className="admin-grid admin-grid--wide">
              <AiUsageDailyBars rows={aiUsage.by_day} />
              <AiUsageAnalysisTable rows={aiUsage.analysis} />
              <MetricTable
                title="Token shape"
                rows={[
                  ["input_tokens", aiUsage.summary.input_tokens],
                  ["output_tokens", aiUsage.summary.output_tokens],
                  ["cached_tokens", aiUsage.summary.cached_tokens],
                  ["reasoning_tokens", aiUsage.summary.reasoning_tokens],
                  ["unpriced_events", aiUsage.summary.unpriced_events],
                ]}
              />
              <MetricTable
                title="Latency"
                rows={[
                  ["avg_latency_ms", aiUsage.summary.avg_latency_ms],
                  ["p95_latency_ms", aiUsage.summary.p95_latency_ms ?? 0],
                ]}
              />
              <AiUsageGroupTable title="Providers" rows={aiUsage.by_provider} labelKey="provider" />
              <AiUsageGroupTable title="Features" rows={aiUsage.by_feature} labelKey="feature" />
              <AiUsageModelTable rows={aiUsage.by_model} />
              <AiUsageUserTable rows={aiUsage.by_user} />
              <AiUsageEventTable rows={aiUsage.recent_events} />
            </div>
          </div>
        ) : null}

        {tab === "deepgram" && deepgramUsage ? (
          <div className="admin-section">
            <form className="admin-inline-form" onSubmit={applyDeepgramUsageFilters}>
              <label>
                <span>Window</span>
                <select
                  value={deepgramUsageFilters.days}
                  onChange={(event) =>
                    setDeepgramUsageFilters((current) => ({
                      ...current,
                      days: Number(event.target.value),
                    }))
                  }
                >
                  <option value={1}>1d</option>
                  <option value={7}>7d</option>
                  <option value={30}>30d</option>
                  <option value={90}>90d</option>
                </select>
              </label>
              <label>
                <span>Rows</span>
                <select
                  value={deepgramUsageFilters.limit}
                  onChange={(event) =>
                    setDeepgramUsageFilters((current) => ({
                      ...current,
                      limit: Number(event.target.value),
                    }))
                  }
                >
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={250}>250</option>
                  <option value={500}>500</option>
                </select>
              </label>
              <button type="submit" disabled={busy}>Apply</button>
            </form>
            <div className="admin-metrics">
              <div>
                <span>Estimated audio {deepgramUsage.window_days}d</span>
                <strong>{fmtMinutes(deepgramUsage.estimated.total_seconds)}</strong>
              </div>
              <div>
                <span>Estimated Deepgram cost</span>
                <strong>{fmtUsd(deepgramUsage.captured.estimated_cost_usd)}</strong>
              </div>
              <div>
                <span>Captured billable</span>
                <strong>{fmtMinutes(deepgramUsage.captured.billable_seconds)}</strong>
              </div>
              <div>
                <span>Provider failures</span>
                <strong>{fmtNumber(deepgramUsage.captured.failed)}</strong>
              </div>
              <div>
                <span>Guard refusals</span>
                <strong>{fmtNumber(deepgramUsage.captured.refused)}</strong>
              </div>
            </div>
            <div className="admin-grid admin-grid--wide">
              <section className="admin-metric-table">
                <h3>Burn analysis</h3>
                <table className="admin-mini-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Finding</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deepgramUsage.analysis.map((item) => (
                      <tr key={item.code}>
                        <td>{item.severity}</td>
                        <td>{item.title}</td>
                        <td>{item.detail}</td>
                      </tr>
                    ))}
                    {deepgramUsage.analysis.length === 0 ? (
                      <tr>
                        <td colSpan={3}>No Deepgram burn risks detected in this window.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </section>
              <MetricTable
                title="Captured ledger"
                rows={[
                  ["events", deepgramUsage.captured.events],
                  ["succeeded", deepgramUsage.captured.succeeded],
                  ["failed", deepgramUsage.captured.failed],
                  ["refused", deepgramUsage.captured.refused],
                  ["provider_402", deepgramUsage.captured.provider_402],
                  ["unpriced_events", deepgramUsage.captured.unpriced_events],
                ]}
              />
              <MetricTable
                title="Historical estimate"
                rows={[
                  ["recordings", deepgramUsage.estimated.recording_count],
                  ["failed_recordings", deepgramUsage.estimated.failed_recordings],
                  ["dictation_entries", deepgramUsage.estimated.dictation_entries],
                  ["recording_words", deepgramUsage.estimated.recording_words],
                  ["dictation_words", deepgramUsage.estimated.dictation_words],
                ]}
              />
              <DeepgramUserTable rows={deepgramUsage.by_user.slice(0, 20)} />
              <DeepgramOperationTable rows={deepgramUsage.by_operation} />
              <DeepgramDayTable rows={deepgramUsage.by_day} />
              <DeepgramRecordingTable rows={deepgramUsage.top_recordings} />
              <DeepgramEventTable rows={deepgramUsage.recent_events} />
            </div>
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

function AiUsageDailyBars({ rows }: { rows: AdminAiUsage["by_day"] }) {
  const maxCost = Math.max(0, ...rows.map((row) => row.estimated_cost_usd));
  const maxTokens = Math.max(0, ...rows.map((row) => row.total_tokens));
  const maxAudio = Math.max(0, ...rows.map((row) => row.billable_seconds));
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Daily AI usage</h3>
      <div className="admin-usage-bars">
        {rows.map((row) => (
          <div key={row.date} className="admin-usage-bars__row">
            <span>{row.date}</span>
            <div className="admin-usage-bars__tracks" aria-label={`AI usage for ${row.date}`}>
              <i
                data-kind="cost"
                style={{ "--bar-width": `${maxCost ? (row.estimated_cost_usd / maxCost) * 100 : 0}%` } as CSSProperties}
              />
              <i
                data-kind="tokens"
                style={{ "--bar-width": `${maxTokens ? (row.total_tokens / maxTokens) * 100 : 0}%` } as CSSProperties}
              />
              <i
                data-kind="audio"
                style={{ "--bar-width": `${maxAudio ? (row.billable_seconds / maxAudio) * 100 : 0}%` } as CSSProperties}
              />
            </div>
            <strong>
              {fmtUsd(row.estimated_cost_usd)} · {fmtNumber(row.total_tokens)} tok ·{" "}
              {fmtMinutes(row.billable_seconds)}
            </strong>
          </div>
        ))}
        {rows.length === 0 ? <p className="muted-text">No AI usage in this window.</p> : null}
      </div>
    </section>
  );
}

function AiUsageAnalysisTable({ rows }: { rows: AdminAiUsage["analysis"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Spend analysis</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Finding</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.code}>
              <td>{row.severity}</td>
              <td>{row.title}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={3}>No AI spend risks detected in this window.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}

function AiUsageGroupTable({
  title,
  rows,
  labelKey,
}: {
  title: string;
  rows: AdminAiUsage["by_provider"];
  labelKey: "provider" | "feature";
}) {
  return (
    <section className="admin-metric-table">
      <h3>{title}</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>{labelKey}</th>
            <th>Events</th>
            <th>Cost</th>
            <th>Tokens</th>
            <th>Audio</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[labelKey] ?? "unknown"}>
              <td>{row[labelKey] ?? "-"}</td>
              <td>{fmtNumber(row.events)}</td>
              <td>{fmtUsd(row.estimated_cost_usd)}</td>
              <td>{fmtNumber(row.total_tokens)}</td>
              <td>{fmtMinutes(row.billable_seconds)}</td>
              <td>{fmtNumber(row.failed_events + row.refused_events)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AiUsageModelTable({ rows }: { rows: AdminAiUsage["by_model"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Models</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Model</th>
            <th>Events</th>
            <th>Cost</th>
            <th>Tokens</th>
            <th>Audio</th>
            <th>Unpriced</th>
            <th>Last</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.provider}:${row.model ?? "unknown"}`}>
              <td>{row.provider}</td>
              <td>{row.model ?? "-"}</td>
              <td>{fmtNumber(row.events)}</td>
              <td>{fmtUsd(row.estimated_cost_usd)}</td>
              <td>{fmtNumber(row.total_tokens)}</td>
              <td>{fmtMinutes(row.billable_seconds)}</td>
              <td>{fmtNumber(row.unpriced_events)}</td>
              <td>{fmtDateTime(row.last_event_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AiUsageUserTable({ rows }: { rows: AdminAiUsage["by_user"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Users by AI usage</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Events</th>
            <th>Cost</th>
            <th>Tokens</th>
            <th>Audio</th>
            <th>Errors</th>
            <th>Unpriced</th>
            <th>Last</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.user_id}>
              <td>{row.email ?? row.user_id}</td>
              <td>{fmtNumber(row.events)}</td>
              <td>{fmtUsd(row.estimated_cost_usd)}</td>
              <td>{fmtNumber(row.total_tokens)}</td>
              <td>{fmtMinutes(row.billable_seconds)}</td>
              <td>{fmtNumber(row.failed_events + row.refused_events)}</td>
              <td>{fmtNumber(row.unpriced_events)}</td>
              <td>{fmtDateTime(row.last_event_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AiUsageEventTable({ rows }: { rows: AdminAiUsage["recent_events"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Recent AI events</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>Feature</th>
            <th>Operation</th>
            <th>Model</th>
            <th>Status</th>
            <th>Cost</th>
            <th>Usage</th>
            <th>Latency</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{fmtDateTime(row.created_at)}</td>
              <td>{row.email ?? row.user_id ?? "-"}</td>
              <td>{row.feature}</td>
              <td>{row.operation}</td>
              <td>{row.model ?? "-"}</td>
              <td>{row.status}</td>
              <td>{row.pricing_status === "priced" ? fmtUsd(row.estimated_cost_usd) : row.pricing_status}</td>
              <td>
                {row.total_tokens ? `${fmtNumber(row.total_tokens)} tok` : fmtMinutes(row.billable_seconds)}
              </td>
              <td>{fmtLatency(row.latency_ms)}</td>
              <td>{row.guard_code ?? row.provider_error_code ?? row.provider_status_code ?? row.error_type ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DeepgramUserTable({ rows }: { rows: AdminDeepgramUsage["by_user"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Users by Deepgram usage</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Cost</th>
            <th>Estimated</th>
            <th>Captured</th>
            <th>Recordings</th>
            <th>Dictation</th>
            <th>Failures</th>
            <th>Unpriced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.user_id}>
              <td>{row.email ?? row.user_id}</td>
              <td>{fmtUsd(row.captured_estimated_cost_usd)}</td>
              <td>{fmtMinutes(row.estimated_total_seconds)}</td>
              <td>{fmtMinutes(row.captured_billable_seconds)}</td>
              <td>{fmtNumber(row.recording_count)}</td>
              <td>{fmtNumber(row.dictation_entries)}</td>
              <td>{fmtNumber(row.captured_failed_events + row.captured_refused_events + row.failed_recordings)}</td>
              <td>{fmtNumber(row.captured_unpriced_events)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DeepgramOperationTable({ rows }: { rows: AdminDeepgramUsage["by_operation"] }) {
  return (
    <section className="admin-metric-table">
      <h3>Operations</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Operation</th>
            <th>Status</th>
            <th>Events</th>
            <th>Cost</th>
            <th>Billable</th>
            <th>Unpriced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.operation}:${row.purpose}:${row.status}`}>
              <td>{row.operation}/{row.purpose}</td>
              <td>{row.status}</td>
              <td>{fmtNumber(row.events)}</td>
              <td>{fmtUsd(row.estimated_cost_usd)}</td>
              <td>{fmtMinutes(row.billable_seconds)}</td>
              <td>{fmtNumber(row.unpriced_events)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DeepgramDayTable({ rows }: { rows: AdminDeepgramUsage["by_day"] }) {
  return (
    <section className="admin-metric-table">
      <h3>Daily usage</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Estimated</th>
            <th>Cost</th>
            <th>Captured</th>
            <th>Failed/refused</th>
            <th>Unpriced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.date}>
              <td>{row.date}</td>
              <td>{fmtMinutes(row.estimated_recording_seconds + row.estimated_dictation_seconds)}</td>
              <td>{fmtUsd(row.captured_estimated_cost_usd)}</td>
              <td>{fmtMinutes(row.captured_billable_seconds)}</td>
              <td>{fmtNumber(row.captured_failed_events + row.captured_refused_events)}</td>
              <td>{fmtNumber(row.captured_unpriced_events)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DeepgramRecordingTable({ rows }: { rows: AdminDeepgramUsage["top_recordings"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Top recordings</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Recording</th>
            <th>User</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Cost</th>
            <th>Events</th>
            <th>Failure</th>
            <th>Unpriced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.recording_id}>
              <td>{row.recording_id.slice(0, 8)}</td>
              <td>{row.email ?? row.user_id}</td>
              <td>{row.status}</td>
              <td>{fmtMinutes(row.duration_seconds)}</td>
              <td>{fmtUsd(row.estimated_cost_usd)}</td>
              <td>{fmtNumber(row.captured_events)}</td>
              <td>{row.failure_code ?? "-"}</td>
              <td>{fmtNumber(row.unpriced_events)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DeepgramEventTable({ rows }: { rows: AdminDeepgramUsage["recent_events"] }) {
  return (
    <section className="admin-metric-table admin-metric-table--wide">
      <h3>Recent Deepgram events</h3>
      <table className="admin-mini-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>Operation</th>
            <th>Status</th>
            <th>Cost</th>
            <th>Billing</th>
            <th>Add-ons</th>
            <th>Billable</th>
            <th>Provider</th>
            <th>Guard</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{fmtDateTime(row.created_at)}</td>
              <td>{row.email ?? row.user_id ?? "-"}</td>
              <td>{row.operation}/{row.purpose}</td>
              <td>{row.status}</td>
              <td>{row.pricing_status === "priced" ? fmtUsd(row.estimated_cost_usd ?? 0) : row.pricing_status}</td>
              <td>{[row.billing_mode, row.language_mode].filter(Boolean).join("/") || "-"}</td>
              <td>{row.addons.length ? row.addons.join(", ") : "-"}</td>
              <td>{fmtMinutes(row.billable_seconds)}</td>
              <td>{row.provider_status_code ?? row.provider_error_code ?? "-"}</td>
              <td>{row.guard_code ?? "-"}</td>
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
