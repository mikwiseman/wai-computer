import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentsPanel } from "./AgentsPanel";

const mockListAgents = vi.fn();
const mockCreateAgent = vi.fn();
const mockUpdateAgent = vi.fn();
const mockStartAgentRun = vi.fn();
const mockListAllAgentRuns = vi.fn();
const mockListAgentActions = vi.fn();
const mockResolveAgentAction = vi.fn();
const mockListReminders = vi.fn();
const mockCreateReminder = vi.fn();
const mockCancelReminder = vi.fn();

vi.mock("@/lib/api", () => ({
  listAgents: (...args: unknown[]) => mockListAgents(...args),
  createAgent: (...args: unknown[]) => mockCreateAgent(...args),
  updateAgent: (...args: unknown[]) => mockUpdateAgent(...args),
  startAgentRun: (...args: unknown[]) => mockStartAgentRun(...args),
  listAllAgentRuns: (...args: unknown[]) => mockListAllAgentRuns(...args),
  listAgentActions: (...args: unknown[]) => mockListAgentActions(...args),
  resolveAgentAction: (...args: unknown[]) => mockResolveAgentAction(...args),
  listReminders: (...args: unknown[]) => mockListReminders(...args),
  createReminder: (...args: unknown[]) => mockCreateReminder(...args),
  cancelReminder: (...args: unknown[]) => mockCancelReminder(...args),
}));

const agent = {
  id: "agent-1",
  name: "Researcher",
  kind: "web",
  trigger_type: "manual",
  config: {},
  autonomy: "propose",
  enabled: true,
  next_run_at: null,
  last_run_at: null,
  created_at: "2026-06-04T12:00:00Z",
  updated_at: "2026-06-04T12:00:00Z",
};

const run = {
  id: "run-1",
  agent_id: "agent-1",
  trigger_key: "manual:agent-1:web",
  trigger_kind: "manual",
  trigger_payload: { objective: "check launch" },
  status: "pending",
  plan: null,
  done_spec: null,
  result: null,
  content_hash: null,
  error: null,
  next_step_idx: 0,
  heartbeat_at: null,
  started_at: null,
  finished_at: null,
  cancel_requested_at: null,
  created_at: "2026-06-04T12:00:00Z",
  updated_at: "2026-06-04T12:00:00Z",
};

const action = {
  id: "action-1",
  agent_id: "agent-1",
  run_id: "run-1",
  step_idx: 1,
  kind: "send",
  tool: "send_message_telegram",
  status: "pending",
  preview: "Send a note",
  recipient: "you",
  expires_at: "2026-06-04T12:15:00Z",
  resolved_at: null,
  receipt: null,
};

const reminder = {
  id: "reminder-1",
  text: "Check launch metrics",
  due_at: "2026-06-04T18:30:00Z",
  status: "pending",
  source: "web",
  source_ref: null,
  sent_at: null,
  failed_at: null,
  error: null,
  metadata: {},
  created_at: "2026-06-04T12:00:00Z",
  updated_at: "2026-06-04T12:00:00Z",
};

describe("AgentsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListAgents.mockResolvedValue({ agents: [agent] });
    mockListAllAgentRuns.mockResolvedValue({ runs: [run] });
    mockListAgentActions.mockResolvedValue({ actions: [action] });
    mockListReminders.mockResolvedValue({ reminders: [reminder] });
    mockCreateAgent.mockResolvedValue(agent);
    mockUpdateAgent.mockResolvedValue({ ...agent, enabled: false });
    mockStartAgentRun.mockResolvedValue(run);
    mockResolveAgentAction.mockResolvedValue({
      action_id: "action-1",
      status: "executed",
      run_status: "done",
      recipient: "you",
    });
    mockCreateReminder.mockResolvedValue(reminder);
    mockCancelReminder.mockResolvedValue({ ...reminder, status: "cancelled" });
  });

  it("loads agents, starts a run, resolves an approval, and creates a reminder", async () => {
    const onError = vi.fn();
    render(<AgentsPanel locale="en" onError={onError} />);

    expect(await screen.findByTestId("agent-agent-1")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("agent-objective-agent-1"), {
      target: { value: "Check launch metrics" },
    });
    fireEvent.click(screen.getByTestId("start-agent-agent-1"));
    await waitFor(() =>
      expect(mockStartAgentRun).toHaveBeenCalledWith("agent-1", {
        trigger_kind: "manual",
        trigger_payload: { objective: "Check launch metrics", source: "web" },
        idempotency_key: expect.stringMatching(/^web:/),
      }),
    );

    fireEvent.click(screen.getByTestId("approve-action-action-1"));
    await waitFor(() =>
      expect(mockResolveAgentAction).toHaveBeenCalledWith(
        "agent-1",
        "run-1",
        "action-1",
        { decision: "once" },
      ),
    );

    fireEvent.change(screen.getByTestId("reminder-text-input"), {
      target: { value: "Review launch" },
    });
    fireEvent.change(screen.getByTestId("reminder-due-input"), {
      target: { value: "2026-06-04T18:30" },
    });
    fireEvent.click(screen.getByTestId("create-reminder-submit"));
    const expectedDueAt = new Date("2026-06-04T18:30").toISOString();
    await waitFor(() =>
      expect(mockCreateReminder).toHaveBeenCalledWith({
        text: "Review launch",
        due_at: expectedDueAt,
        source: "web",
        metadata: { origin: "agents_panel" },
      }),
    );
  });

  it("creates a simple note agent", async () => {
    const onError = vi.fn();
    render(<AgentsPanel locale="en" onError={onError} />);
    await screen.findByTestId("agent-agent-1");

    fireEvent.change(screen.getByTestId("agent-name-input"), {
      target: { value: "Daily check" },
    });
    fireEvent.change(screen.getByTestId("agent-step-input"), {
      target: { value: "Write launch notes" },
    });
    fireEvent.click(screen.getByTestId("create-agent-submit"));

    await waitFor(() =>
      expect(mockCreateAgent).toHaveBeenCalledWith({
        name: "Daily check",
        kind: "web",
        trigger_type: "manual",
        config: {
          steps: [{ tool: "note", args: { text: "Write launch notes" } }],
        },
      }),
    );
  });
});
