"use client";

import { FormEvent, useState } from "react";
import { createAdminPromoCode, type AdminPromoCode } from "@/lib/admin";

export function AdminPromoCodesClient() {
  const [adminPassword, setAdminPassword] = useState("");
  const [code, setCode] = useState("");
  const [prefix, setPrefix] = useState("WAI");
  const [period, setPeriod] = useState<"month" | "year">("month");
  const [durationDays, setDurationDays] = useState(30);
  const [maxRedemptions, setMaxRedemptions] = useState(1);
  const [expiresDays, setExpiresDays] = useState(30);
  const [note, setNote] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [result, setResult] = useState<AdminPromoCode | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInFlight(true);
    setResult(null);
    setError(null);
    try {
      const created = await createAdminPromoCode({
        adminPassword,
        code: code.trim() || null,
        prefix: prefix.trim() || "WAI",
        plan: "pro",
        billing_period: period,
        duration_days: durationDays,
        max_redemptions: maxRedemptions,
        expires_days: expiresDays,
        note: note.trim() || null,
      });
      setResult(created);
      setCode("");
      setNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось сгенерировать промокод.");
    } finally {
      setInFlight(false);
    }
  }

  return (
    <main className="admin-page">
      <section className="admin-panel" aria-labelledby="admin-promos-title">
        <div className="admin-heading">
          <p>WaiComputer Admin</p>
          <h1 id="admin-promos-title">Промокоды</h1>
        </div>

        <form className="admin-form" onSubmit={handleSubmit}>
          <label>
            <span>Админ-пароль</span>
            <input
              type="password"
              value={adminPassword}
              onChange={(event) => setAdminPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          <div className="admin-form-grid">
            <label>
              <span>Код</span>
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="Оставь пустым для автогенерации"
              />
            </label>
            <label>
              <span>Префикс</span>
              <input
                value={prefix}
                onChange={(event) => setPrefix(event.target.value)}
                required
                maxLength={16}
              />
            </label>
          </div>

          <div className="admin-form-grid">
            <label>
              <span>Период</span>
              <select
                value={period}
                onChange={(event) => setPeriod(event.target.value as "month" | "year")}
              >
                <option value="month">Месяц</option>
                <option value="year">Год</option>
              </select>
            </label>
            <label>
              <span>Срок Pro, дней</span>
              <input
                type="number"
                min={1}
                max={3650}
                value={durationDays}
                onChange={(event) => setDurationDays(Number(event.target.value))}
                required
              />
            </label>
          </div>

          <div className="admin-form-grid">
            <label>
              <span>Лимит активаций</span>
              <input
                type="number"
                min={1}
                max={100000}
                value={maxRedemptions}
                onChange={(event) => setMaxRedemptions(Number(event.target.value))}
                required
              />
            </label>
            <label>
              <span>Код истекает через, дней</span>
              <input
                type="number"
                min={1}
                max={3650}
                value={expiresDays}
                onChange={(event) => setExpiresDays(Number(event.target.value))}
                required
              />
            </label>
          </div>

          <label>
            <span>Заметка</span>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={500}
              placeholder="Например: тестировщики, май 2026"
            />
          </label>

          <button type="submit" className="admin-primary" disabled={inFlight}>
            {inFlight ? "Генерируем..." : "Сгенерировать"}
          </button>
        </form>

        {error ? <p className="admin-error">{error}</p> : null}

        {result ? (
          <div className="admin-result" aria-live="polite">
            <span>Промокод</span>
            <strong>{result.code}</strong>
            <p>Показывается один раз. В базе хранится только хэш.</p>
            <dl>
              <div>
                <dt>План</dt>
                <dd>{result.plan}</dd>
              </div>
              <div>
                <dt>Срок</dt>
                <dd>{result.duration_days} дней</dd>
              </div>
              <div>
                <dt>Активации</dt>
                <dd>
                  {result.redeemed_count} / {result.max_redemptions}
                </dd>
              </div>
            </dl>
          </div>
        ) : null}
      </section>
    </main>
  );
}
