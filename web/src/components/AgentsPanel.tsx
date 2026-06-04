"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelReminder,
  createAgent,
  createReminder,
  listAgentActions,
  listAgents,
  listAllAgentRuns,
  listReminders,
  resolveAgentAction,
  startAgentRun,
  updateAgent,
} from "@/lib/api";
import type { Agent, AgentAction, AgentRun, Recording, Reminder } from "@/lib/types";
import { CompanionPanel } from "./CompanionPanel";

type Locale = "en" | "ru";

interface AgentsPanelProps {
  locale: Locale;
  recordings: Recording[];
  onError: (message: string) => void;
}

const COPY = {
  en: {
    controlsTitle: "Agent controls",
    controlsSubtitle: "Saved agents, approvals, reminders, and manual runs.",
    refresh: "Refresh",
    namePlaceholder: "Agent name",
    stepPlaceholder: "First note step",
    create: "Create",
    emptyAgents: "No agents yet.",
    runPlaceholder: "Objective for this run",
    run: "Run",
    enabled: "Enabled",
    disabled: "Disabled",
    pause: "Pause",
    resume: "Resume",
    runsTitle: "Recent runs",
    approvalsTitle: "Pending approvals",
    approve: "Approve",
    reject: "Reject",
    remindersTitle: "Reminders",
    reminderText: "Reminder text",
    reminderDue: "Due date and time",
    addReminder: "Add reminder",
    cancel: "Cancel",
    emptyRuns: "No runs yet.",
    emptyApprovals: "No approvals waiting.",
    emptyReminders: "No reminders yet.",
    loading: "Loading agents.",
    created: "Agent created.",
    started: "Agent run started.",
    updated: "Agent updated.",
    approved: "Approval resolved.",
    reminderCreated: "Reminder created.",
    reminderCancelled: "Reminder cancelled.",
    enterAgentName: "Enter an agent name.",
    enterStepText: "Enter the first note step.",
    enterObjective: "Enter an objective.",
    enterReminderText: "Enter reminder text.",
    enterReminderDue: "Choose a reminder time.",
    missingActionScope: "This approval is missing agent run context.",
  },
  ru: {
    controlsTitle: "Управление агентами",
    controlsSubtitle: "Сохраненные агенты, подтверждения, напоминания и ручные запуски.",
    refresh: "Обновить",
    namePlaceholder: "Название агента",
    stepPlaceholder: "Первый шаг-заметка",
    create: "Создать",
    emptyAgents: "Агентов пока нет.",
    runPlaceholder: "Задача для запуска",
    run: "Запустить",
    enabled: "Включен",
    disabled: "Выключен",
    pause: "Выключить",
    resume: "Включить",
    runsTitle: "Последние запуски",
    approvalsTitle: "Ожидают подтверждения",
    approve: "Подтвердить",
    reject: "Отклонить",
    remindersTitle: "Напоминания",
    reminderText: "Текст напоминания",
    reminderDue: "Дата и время",
    addReminder: "Добавить",
    cancel: "Отменить",
    emptyRuns: "Запусков пока нет.",
    emptyApprovals: "Нет действий на подтверждение.",
    emptyReminders: "Напоминаний пока нет.",
    loading: "Загружаю агентов.",
    created: "Агент создан.",
    started: "Запуск агента создан.",
    updated: "Агент обновлен.",
    approved: "Подтверждение обработано.",
    reminderCreated: "Напоминание создано.",
    reminderCancelled: "Напоминание отменено.",
    enterAgentName: "Введи название агента.",
    enterStepText: "Введи первый шаг-заметку.",
    enterObjective: "Введи задачу.",
    enterReminderText: "Введи текст напоминания.",
    enterReminderDue: "Выбери время напоминания.",
    missingActionScope: "У подтверждения нет контекста запуска агента.",
  },
} as const;

function formatDate(value: string | null, locale: Locale): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat(locale === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function runLabel(run: AgentRun, agentsById: Map<string, Agent>): string {
  return agentsById.get(run.agent_id)?.name ?? run.agent_id.slice(0, 8);
}

export function AgentsPanel({ locale, recordings, onError }: AgentsPanelProps) {
  const copy = COPY[locale];
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [newAgentName, setNewAgentName] = useState("");
  const [newStepText, setNewStepText] = useState("");
  const [objectives, setObjectives] = useState<Record<string, string>>({});
  const [reminderText, setReminderText] = useState("");
  const [reminderDueAt, setReminderDueAt] = useState("");

  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agentList, runList, actionList, reminderList] = await Promise.all([
        listAgents({ limit: 50 }),
        listAllAgentRuns({ limit: 20 }),
        listAgentActions({ status: "pending", limit: 20 }),
        listReminders({ status: "all", limit: 20 }),
      ]);
      setAgents(agentList.agents);
      setRuns(runList.runs);
      setActions(actionList.actions);
      setReminders(reminderList.reminders);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreateAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newAgentName.trim();
    const stepText = newStepText.trim();
    if (!name) {
      onError(copy.enterAgentName);
      return;
    }
    if (!stepText) {
      onError(copy.enterStepText);
      return;
    }
    setBusy("create-agent");
    try {
      await createAgent({
        name,
        kind: "web",
        trigger_type: "manual",
        config: {
          steps: [{ tool: "note", args: { text: stepText } }],
        },
      });
      setNewAgentName("");
      setNewStepText("");
      onError(copy.created);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleStartRun(agent: Agent) {
    const objective = (objectives[agent.id] ?? "").trim();
    if (!objective) {
      onError(copy.enterObjective);
      return;
    }
    setBusy(`run-${agent.id}`);
    try {
      await startAgentRun(agent.id, {
        trigger_kind: "manual",
        trigger_payload: { objective, source: "web" },
        idempotency_key: `web:${Date.now()}`,
      });
      setObjectives((current) => ({ ...current, [agent.id]: "" }));
      onError(copy.started);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleToggleAgent(agent: Agent) {
    setBusy(`toggle-${agent.id}`);
    try {
      await updateAgent(agent.id, { enabled: !agent.enabled });
      onError(copy.updated);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleResolveAction(action: AgentAction, decision: "once" | "reject") {
    if (!action.agent_id || !action.run_id) {
      onError(copy.missingActionScope);
      return;
    }
    setBusy(`${decision}-${action.id}`);
    try {
      await resolveAgentAction(action.agent_id, action.run_id, action.id, { decision });
      onError(copy.approved);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleCreateReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = reminderText.trim();
    if (!text) {
      onError(copy.enterReminderText);
      return;
    }
    if (!reminderDueAt) {
      onError(copy.enterReminderDue);
      return;
    }
    setBusy("create-reminder");
    try {
      await createReminder({
        text,
        due_at: new Date(reminderDueAt).toISOString(),
        source: "web",
        metadata: { origin: "agents_panel" },
      });
      setReminderText("");
      setReminderDueAt("");
      onError(copy.reminderCreated);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleCancelReminder(reminder: Reminder) {
    setBusy(`cancel-reminder-${reminder.id}`);
    try {
      await cancelReminder(reminder.id);
      onError(copy.reminderCancelled);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="agents-panel" data-testid="agents-panel">
      <CompanionPanel recordings={recordings} locale={locale} />

      <details className="agents-controls" data-testid="agents-controls">
        <summary>
          <span>
            <strong>{copy.controlsTitle}</strong>
            <small>{copy.controlsSubtitle}</small>
          </span>
        </summary>

        <header className="panel-header agents-panel__header">
          <button
            type="button"
            className="ghost-button compact-button"
            data-testid="agents-refresh"
            onClick={() => void load()}
            disabled={loading}
          >
            {copy.refresh}
          </button>
        </header>

        {loading ? <p className="settings-note">{copy.loading}</p> : null}

        <div className="agents-grid">
        <section className="agents-section">
          <header className="agents-section__header">
            <h4>{copy.controlsTitle}</h4>
          </header>
          <form className="agents-inline-form" onSubmit={handleCreateAgent}>
            <input
              data-testid="agent-name-input"
              value={newAgentName}
              placeholder={copy.namePlaceholder}
              onChange={(event) => setNewAgentName(event.target.value)}
            />
            <input
              data-testid="agent-step-input"
              value={newStepText}
              placeholder={copy.stepPlaceholder}
              onChange={(event) => setNewStepText(event.target.value)}
            />
            <button
              type="submit"
              className="ghost-button compact-button"
              data-testid="create-agent-submit"
              disabled={busy === "create-agent"}
            >
              {copy.create}
            </button>
          </form>

          {agents.length === 0 ? (
            <div className="empty-state">
              <h3>{copy.emptyAgents}</h3>
            </div>
          ) : (
            <ul className="agents-list">
              {agents.map((agent) => (
                <li key={agent.id} className="agents-list__item" data-testid={`agent-${agent.id}`}>
                  <div className="agents-list__main">
                    <strong>{agent.name}</strong>
                    <small>
                      {agent.kind} / {agent.enabled ? copy.enabled : copy.disabled}
                    </small>
                  </div>
                  <div className="agents-run-row">
                    <input
                      data-testid={`agent-objective-${agent.id}`}
                      value={objectives[agent.id] ?? ""}
                      placeholder={copy.runPlaceholder}
                      onChange={(event) =>
                        setObjectives((current) => ({
                          ...current,
                          [agent.id]: event.target.value,
                        }))
                      }
                    />
                    <button
                      type="button"
                      className="ghost-button compact-button"
                      data-testid={`start-agent-${agent.id}`}
                      disabled={!agent.enabled || busy === `run-${agent.id}`}
                      onClick={() => void handleStartRun(agent)}
                    >
                      {copy.run}
                    </button>
                    <button
                      type="button"
                      className="ghost-button compact-button"
                      data-testid={`toggle-agent-${agent.id}`}
                      disabled={busy === `toggle-${agent.id}`}
                      onClick={() => void handleToggleAgent(agent)}
                    >
                      {agent.enabled ? copy.pause : copy.resume}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="agents-section">
          <header className="agents-section__header">
            <h4>{copy.approvalsTitle}</h4>
          </header>
          {actions.length === 0 ? (
            <div className="empty-state">
              <h3>{copy.emptyApprovals}</h3>
            </div>
          ) : (
            <ul className="agents-list">
              {actions.map((action) => (
                <li key={action.id} className="agents-list__item">
                  <div className="agents-list__main">
                    <strong>{action.tool}</strong>
                    <small>
                      {action.preview} / {formatDate(action.expires_at, locale)}
                    </small>
                  </div>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="ghost-button compact-button"
                      data-testid={`approve-action-${action.id}`}
                      disabled={busy === `once-${action.id}`}
                      onClick={() => void handleResolveAction(action, "once")}
                    >
                      {copy.approve}
                    </button>
                    <button
                      type="button"
                      className="ghost-button compact-button danger-button"
                      data-testid={`reject-action-${action.id}`}
                      disabled={busy === `reject-${action.id}`}
                      onClick={() => void handleResolveAction(action, "reject")}
                    >
                      {copy.reject}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="agents-section">
          <header className="agents-section__header">
            <h4>{copy.runsTitle}</h4>
          </header>
          {runs.length === 0 ? (
            <div className="empty-state">
              <h3>{copy.emptyRuns}</h3>
            </div>
          ) : (
            <ul className="agents-list">
              {runs.map((run) => (
                <li key={run.id} className="agents-list__item">
                  <div className="agents-list__main">
                    <strong>{runLabel(run, agentsById)}</strong>
                    <small>
                      {run.status} / {formatDate(run.created_at, locale)}
                    </small>
                  </div>
                  {run.error ? <p className="settings-note">{run.error}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="agents-section">
          <header className="agents-section__header">
            <h4>{copy.remindersTitle}</h4>
          </header>
          <form className="agents-inline-form" onSubmit={handleCreateReminder}>
            <input
              data-testid="reminder-text-input"
              value={reminderText}
              placeholder={copy.reminderText}
              onChange={(event) => setReminderText(event.target.value)}
            />
            <input
              data-testid="reminder-due-input"
              type="datetime-local"
              value={reminderDueAt}
              aria-label={copy.reminderDue}
              onChange={(event) => setReminderDueAt(event.target.value)}
            />
            <button
              type="submit"
              className="ghost-button compact-button"
              data-testid="create-reminder-submit"
              disabled={busy === "create-reminder"}
            >
              {copy.addReminder}
            </button>
          </form>
          {reminders.length === 0 ? (
            <div className="empty-state">
              <h3>{copy.emptyReminders}</h3>
            </div>
          ) : (
            <ul className="agents-list">
              {reminders.map((reminder) => (
                <li key={reminder.id} className="agents-list__item">
                  <div className="agents-list__main">
                    <strong>{reminder.text}</strong>
                    <small>
                      {reminder.status} / {formatDate(reminder.due_at, locale)}
                    </small>
                  </div>
                  {reminder.status === "pending" ? (
                    <button
                      type="button"
                      className="ghost-button compact-button danger-button"
                      data-testid={`cancel-reminder-${reminder.id}`}
                      disabled={busy === `cancel-reminder-${reminder.id}`}
                      onClick={() => void handleCancelReminder(reminder)}
                    >
                      {copy.cancel}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
        </div>
      </details>
    </section>
  );
}
