"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  getDataOwnershipMap,
  getSystemInfo,
  startSelfHostProvision,
} from "@/lib/api";
import type {
  DataOwnershipMap,
  SelfHostProvisionResponse,
  SystemInfo,
} from "@/lib/types";

type Locale = "en" | "ru";
type AuthMethod = "ssh_key" | "password";

interface ServerDataSectionProps {
  locale?: Locale;
  provisioning?: "active" | "account_required";
}

const COPY = {
  en: {
    title: "Server & Data",
    intro: "Choose where WaiComputer runs and verify what belongs to you.",
    loading: "Loading server information...",
    cloud: "Wai Cloud",
    selfHost: "My server",
    provisioning: "Provisioning",
    serverUrl: "Current server",
    mcp: "MCP URL",
    dataPolicy: "Data policy",
    audioPolicy: "Original audio is deleted after transcription unless retention is explicitly enabled later.",
    owned: "Owned exportable records",
    artifacts: "Files and artifacts",
    reconnect: "Needs reconnect",
    provisionTitle: "Move to my server",
    accountRequiredTitle: "Create an account first",
    accountRequiredBody:
      "The VPS check is tied to your account so we can show progress, migration status, and reconnect steps safely.",
    createAccount: "Create account",
    signIn: "Sign in",
    hostname: "Public domain (optional)",
    hostnameHelp: "Use this only if DNS is already pointed to the VPS. You can add it later.",
    optionalDomain: "Optional public domain",
    ip: "VPS IP address",
    ipHelp: "This is the server IP address from your VPS provider. Wai uses it for the SSH check.",
    user: "SSH user",
    method: "SSH method",
    publicKey: "SSH public key",
    publicKeyHelp: "Use a public key that already has access to the VPS.",
    password: "Temporary password",
    start: "Check setup",
    starting: "Checking...",
    checklistTitle: "Setup checklist",
    checklistIntro:
      "Create the provider keys before setup. Wai keeps those keys server-side on your server, never in browser or mobile clients.",
    checklistItems: [
      {
        title: "Ubuntu VPS",
        body: "A fresh Ubuntu server with a public IP. A domain is optional and can be added later.",
      },
      {
        title: "Temporary root password or SSH public key",
        body: "Use the provider's first-login password once, or paste a public key that already works on the VPS.",
      },
      {
        title: "Provider API keys",
        body: "Deepgram for speech-to-text, OpenAI for embeddings and companion tasks, Cerebras for summaries and cleanup.",
      },
    ],
    providerLinks: "Key pages",
    deepgram: "Deepgram",
    openai: "OpenAI",
    cerebras: "Cerebras",
    exportTitle: "Export and import",
    exportBody:
      "The migration map includes recordings, transcripts, summaries, memories, uploads, settings, usage history, and API metadata. Server-bound sessions and OAuth tokens are regenerated on the new server.",
  },
  ru: {
    title: "Сервер и данные",
    intro: "Выберите, где работает WaiComputer, и проверьте, какие данные принадлежат вам.",
    loading: "Загружаем информацию о сервере...",
    cloud: "Wai Cloud",
    selfHost: "Мой сервер",
    provisioning: "Настройка",
    serverUrl: "Текущий сервер",
    mcp: "MCP URL",
    dataPolicy: "Политика данных",
    audioPolicy: "Исходное аудио удаляется после транскрипции, если позже явно не включить хранение.",
    owned: "Экспортируемые записи",
    artifacts: "Файлы и артефакты",
    reconnect: "Нужно переподключить",
    provisionTitle: "Перенести на мой сервер",
    accountRequiredTitle: "Сначала создайте аккаунт",
    accountRequiredBody:
      "Проверка VPS привязана к аккаунту, чтобы безопасно показать прогресс, статус миграции и шаги переподключения.",
    createAccount: "Создать аккаунт",
    signIn: "Войти",
    hostname: "Публичный домен (необязательно)",
    hostnameHelp: "Укажите, только если DNS уже направлен на VPS. Домен можно добавить позже.",
    optionalDomain: "Необязательный публичный домен",
    ip: "IP VPS",
    ipHelp: "Это IP-адрес сервера от провайдера VPS. Wai использует его для проверки SSH.",
    user: "SSH пользователь",
    method: "Метод SSH",
    publicKey: "Публичный SSH ключ",
    publicKeyHelp: "Используйте публичный ключ, у которого уже есть доступ к VPS.",
    password: "Временный пароль",
    start: "Проверить настройку",
    starting: "Проверяем...",
    checklistTitle: "Чеклист настройки",
    checklistIntro:
      "Создайте ключи провайдеров до настройки. Wai хранит эти ключи только на вашем сервере, а не в браузере или мобильных приложениях.",
    checklistItems: [
      {
        title: "Ubuntu VPS",
        body: "Новый Ubuntu-сервер с публичным IP. Домен необязателен, его можно добавить позже.",
      },
      {
        title: "Временный пароль root или публичный SSH-ключ",
        body: "Используйте первый пароль от провайдера один раз или вставьте публичный ключ, который уже работает на VPS.",
      },
      {
        title: "API-ключи провайдеров",
        body: "Deepgram для распознавания речи, OpenAI для эмбеддингов и задач Companion, Cerebras для саммари и очистки диктовки.",
      },
    ],
    providerLinks: "Страницы ключей",
    deepgram: "Deepgram",
    openai: "OpenAI",
    cerebras: "Cerebras",
    exportTitle: "Экспорт и импорт",
    exportBody:
      "Карта миграции включает записи, транскрипты, саммари, память, загрузки, настройки, историю использования и API-метаданные. Сессии и OAuth-токены пересоздаются на новом сервере.",
  },
} as const;

function countByClassification(map: DataOwnershipMap | null, classification: string): number {
  if (!map) return 0;
  return [...map.tables, ...map.artifacts].filter(
    (entry) => entry.classification === classification,
  ).length;
}

function countReconnectRequired(map: DataOwnershipMap | null): number {
  if (!map) return 0;
  return [...map.tables, ...map.artifacts].filter((entry) => entry.requires_reconnect).length;
}

function serverLabel(info: SystemInfo | null, locale: Locale): string {
  if (!info) return "";
  if (info.deployment_mode === "self_host") return COPY[locale].selfHost;
  if (info.deployment_mode === "provisioning") return COPY[locale].provisioning;
  return COPY[locale].cloud;
}

export function ServerDataSection({
  locale = "en",
  provisioning = "active",
}: ServerDataSectionProps) {
  const copy = COPY[locale];
  const shouldLoadServerData = provisioning === "active";
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [dataMap, setDataMap] = useState<DataOwnershipMap | null>(null);
  const [loading, setLoading] = useState(shouldLoadServerData);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SelfHostProvisionResponse | null>(null);
  const [authMethod, setAuthMethod] = useState<AuthMethod>("password");
  const [form, setForm] = useState({
    hostname: "",
    vps_ip: "",
    ssh_username: "root",
    ssh_public_key: "",
    ssh_password: "",
  });

  useEffect(() => {
    if (!shouldLoadServerData) {
      setInfo(null);
      setDataMap(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [systemInfo, ownership] = await Promise.all([
          getSystemInfo(),
          getDataOwnershipMap(),
        ]);
        if (!cancelled) {
          setInfo(systemInfo);
          setDataMap(ownership);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load server data.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [shouldLoadServerData]);

  const ownedCount = useMemo(() => countByClassification(dataMap, "owned_exportable"), [dataMap]);
  const reconnectCount = useMemo(() => countReconnectRequired(dataMap), [dataMap]);

  async function submitProvision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const trimmedHostname = form.hostname.trim();
      const response = await startSelfHostProvision({
        hostname: trimmedHostname ? trimmedHostname : null,
        vps_ip: form.vps_ip.trim(),
        ssh_username: form.ssh_username.trim(),
        auth_method: authMethod,
        ssh_public_key: authMethod === "ssh_key" ? form.ssh_public_key.trim() : null,
        ssh_password: authMethod === "password" ? form.ssh_password : null,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start setup.");
    } finally {
      if (authMethod === "password") {
        setForm((current) => ({ ...current, ssh_password: "" }));
      }
      setSubmitting(false);
    }
  }

  return (
    <section
      id="server-data"
      className="settings-form server-data-section"
      data-testid="server-data-section"
    >
      <div className="server-data-head">
        <div>
          <h3>{copy.title}</h3>
          <p className="settings-note">{copy.intro}</p>
        </div>
        {info ? <span className="server-data-badge">{serverLabel(info, locale)}</span> : null}
      </div>

      {loading ? <p className="settings-note">{copy.loading}</p> : null}
      {error ? (
        <p className="settings-note server-data-error" role="alert">
          {error}
        </p>
      ) : null}

      {info ? (
        <div className="server-data-grid">
          <div>
            <span>{copy.serverUrl}</span>
            <strong>{info.public_base_url}</strong>
          </div>
          <div>
            <span>{copy.mcp}</span>
            <code>{info.mcp_url}</code>
          </div>
          <div>
            <span>{copy.dataPolicy}</span>
            <strong>{copy.audioPolicy}</strong>
          </div>
        </div>
      ) : null}

      {dataMap ? (
        <div className="server-data-metrics">
          <div>
            <strong>{ownedCount}</strong>
            <span>{copy.owned}</span>
          </div>
          <div>
            <strong>{dataMap.artifacts.length}</strong>
            <span>{copy.artifacts}</span>
          </div>
          <div>
            <strong>{reconnectCount}</strong>
            <span>{copy.reconnect}</span>
          </div>
        </div>
      ) : null}

      <div className="server-data-checklist">
        <h4>{copy.checklistTitle}</h4>
        <p className="settings-note">{copy.checklistIntro}</p>
        <ul>
          {copy.checklistItems.map((item) => (
            <li key={item.title}>
              <strong>{item.title}</strong>
              <span>{item.body}</span>
            </li>
          ))}
        </ul>
        <p className="settings-note server-data-provider-links">
          {copy.providerLinks}:{" "}
          <a
            href="https://developers.deepgram.com/guides/fundamentals/make-your-first-api-request"
            target="_blank"
            rel="noreferrer"
          >
            {copy.deepgram}
          </a>
          {", "}
          <a
            href="https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key"
            target="_blank"
            rel="noreferrer"
          >
            {copy.openai}
          </a>
          {", "}
          <a
            href="https://inference-docs.cerebras.ai/console/api-keys"
            target="_blank"
            rel="noreferrer"
          >
            {copy.cerebras}
          </a>
        </p>
      </div>

      {provisioning === "account_required" ? (
        <div className="server-data-account-required">
          <h4>{copy.accountRequiredTitle}</h4>
          <p className="settings-note">{copy.accountRequiredBody}</p>
          <div className="server-data-actions">
            <Link href="/register" className="primary-button">
              {copy.createAccount}
            </Link>
            <Link href="/login" className="ghost-button">
              {copy.signIn}
            </Link>
          </div>
        </div>
      ) : (
        <form className="server-data-provision" onSubmit={submitProvision}>
          <h4>{copy.provisionTitle}</h4>
          <label>
            <span>{copy.ip}</span>
            <input
              aria-label={copy.ip}
              value={form.vps_ip}
              onChange={(event) =>
                setForm((current) => ({ ...current, vps_ip: event.target.value }))
              }
              required
              inputMode="numeric"
              placeholder="203.0.113.10"
            />
            <small className="server-data-help">{copy.ipHelp}</small>
          </label>
          <label>
            <span>{copy.user}</span>
            <input
              aria-label={copy.user}
              value={form.ssh_username}
              onChange={(event) =>
                setForm((current) => ({ ...current, ssh_username: event.target.value }))
              }
              required
            />
          </label>
          <label>
            <span>{copy.method}</span>
            <select
              aria-label={copy.method}
              value={authMethod}
              onChange={(event) => setAuthMethod(event.target.value as AuthMethod)}
            >
              <option value="password">Password</option>
              <option value="ssh_key">SSH key</option>
            </select>
          </label>
          {authMethod === "ssh_key" ? (
            <label className="server-data-wide">
              <span>{copy.publicKey}</span>
              <textarea
                aria-label={copy.publicKey}
                value={form.ssh_public_key}
                onChange={(event) =>
                  setForm((current) => ({ ...current, ssh_public_key: event.target.value }))
                }
                placeholder="ssh-ed25519 AAAA..."
                required
                rows={3}
              />
              <small className="server-data-help">{copy.publicKeyHelp}</small>
            </label>
          ) : (
            <label>
              <span>{copy.password}</span>
              <input
                aria-label={copy.password}
                type="password"
                value={form.ssh_password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, ssh_password: event.target.value }))
                }
                autoComplete="off"
                required
              />
            </label>
          )}
          <details className="server-data-advanced">
            <summary>{copy.optionalDomain}</summary>
            <label>
              <span>{copy.hostname}</span>
              <input
                aria-label={copy.hostname}
                value={form.hostname}
                onChange={(event) =>
                  setForm((current) => ({ ...current, hostname: event.target.value }))
                }
                placeholder="demo.example.com"
              />
              <small className="server-data-help">{copy.hostnameHelp}</small>
            </label>
          </details>
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? copy.starting : copy.start}
          </button>
        </form>
      )}

      {result ? (
        <div className="server-data-result" data-testid="server-provision-result">
          <strong>{result.hostname ?? result.vps_ip}</strong>
          <p>{result.message}</p>
          <ol>
            {result.steps.map((step) => (
              <li key={step.id}>
                <span>{step.label}</span>
                <code>{step.status}</code>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="server-data-export">
        <h4>{copy.exportTitle}</h4>
        <p className="settings-note">{copy.exportBody}</p>
      </div>
    </section>
  );
}
