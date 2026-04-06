import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentsView } from "./AgentsView";

vi.mock("@/lib/api", () => ({
  listAgents: vi.fn(),
  createAgent: vi.fn(),
  runAgent: vi.fn(),
  deleteAgent: vi.fn(),
}));

vi.mock("@/lib/http", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    payload: unknown;
    constructor(msg: string, status: number) {
      super(msg);
      this.status = status;
      this.payload = null;
    }
  },
}));

const { listAgents, createAgent, runAgent, deleteAgent } = await import(
  "@/lib/api"
);
const mockListAgents = vi.mocked(listAgents);
const mockCreateAgent = vi.mocked(createAgent);
const mockRunAgent = vi.mocked(runAgent);
const mockDeleteAgent = vi.mocked(deleteAgent);

describe("AgentsView", () => {
  beforeEach(() => {
    mockListAgents.mockReset();
    mockCreateAgent.mockReset();
    mockRunAgent.mockReset();
    mockDeleteAgent.mockReset();
  });

  it("renders empty state", async () => {
    mockListAgents.mockResolvedValue([]);
    render(<AgentsView />);
    await waitFor(() => {
      expect(screen.getByText("No agents yet. Create your first one above.")).toBeTruthy();
    });
  });

  it("renders agent list", async () => {
    const agents = [
      {
        id: "a1",
        name: "HN Monitor",
        description: "Check HN for AI news",
        schedule_type: "cron",
        cron_expression: "0 9 * * *",
        status: "active",
        delivery_channel: "api",
        run_count: 5,
        error_count: 0,
        last_run_at: "2026-03-30T09:00:00Z",
        next_run_at: "2026-03-31T09:00:00Z",
        last_result: "Found 3 articles",
        last_error: null,
        created_at: "2026-03-25T10:00:00Z",
      },
    ];
    // Mock both the useEffect call and the loadAgents call
    mockListAgents.mockResolvedValue(agents);
    render(<AgentsView />);
    await waitFor(() => {
      expect(screen.getByText(/HN Monitor/)).toBeTruthy();
    }, { timeout: 3000 });
  });

  it("creates agent", async () => {
    mockListAgents.mockResolvedValue([]);
    mockCreateAgent.mockResolvedValue({
      id: "new-1",
      name: "Test Agent",
      description: "test",
      schedule_type: "manual",
      cron_expression: null,
      status: "active",
      delivery_channel: "api",
      run_count: 0,
      error_count: 0,
      last_run_at: null,
      next_run_at: null,
      last_result: null,
      last_error: null,
      created_at: "2026-03-31T10:00:00Z",
    });

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/HackerNews/i)).toBeTruthy();
    });

    const input = screen.getByPlaceholderText(/HackerNews/i);
    await user.type(input, "monitor AI news daily");
    await user.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(mockCreateAgent).toHaveBeenCalledWith("monitor AI news daily");
    });
  });

  it("creates agent via Enter key", async () => {
    mockListAgents.mockResolvedValue([]);
    mockCreateAgent.mockResolvedValue({
      id: "new-2", name: "Enter Agent", description: "test",
      schedule_type: "manual", cron_expression: null, status: "active",
      delivery_channel: "api", run_count: 0, error_count: 0,
      last_run_at: null, next_run_at: null, last_result: null,
      last_error: null, created_at: "2026-04-01T10:00:00Z",
    });

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/HackerNews/i)).toBeTruthy();
    });

    const input = screen.getByPlaceholderText(/HackerNews/i);
    await user.type(input, "test agent{Enter}");

    await waitFor(() => {
      expect(mockCreateAgent).toHaveBeenCalledWith("test agent");
    });
  });

  it("runs an agent", async () => {
    const agents = [{
      id: "a1", name: "Runner", description: "runs stuff",
      schedule_type: "manual", cron_expression: null, status: "active",
      delivery_channel: "api", run_count: 0, error_count: 0,
      last_run_at: null, next_run_at: null, last_result: null,
      last_error: null, created_at: "2026-03-30T10:00:00Z",
    }];
    mockListAgents.mockResolvedValue(agents);
    mockRunAgent.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText(/Runner/)).toBeTruthy();
    });

    await user.click(screen.getByText("Run"));

    await waitFor(() => {
      expect(mockRunAgent).toHaveBeenCalledWith("a1");
    });
    expect(screen.getByText(/Agent triggered/)).toBeTruthy();
  });

  it("deletes an agent", async () => {
    const agents = [{
      id: "a1", name: "Deletable", description: "to delete",
      schedule_type: "manual", cron_expression: null, status: "active",
      delivery_channel: "api", run_count: 0, error_count: 0,
      last_run_at: null, next_run_at: null, last_result: null,
      last_error: null, created_at: "2026-03-30T10:00:00Z",
    }];
    mockListAgents.mockResolvedValueOnce(agents).mockResolvedValueOnce([]);
    mockDeleteAgent.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText(/Deletable/)).toBeTruthy();
    });

    await user.click(screen.getByText("Delete"));

    await waitFor(() => {
      expect(mockDeleteAgent).toHaveBeenCalledWith("a1");
    });
  });

  it("shows error on create failure", async () => {
    mockListAgents.mockResolvedValue([]);
    mockCreateAgent.mockRejectedValue(new Error("Create failed"));

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/HackerNews/i)).toBeTruthy();
    });

    await user.type(screen.getByPlaceholderText(/HackerNews/i), "failing agent");
    await user.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(screen.getByText("Create failed")).toBeTruthy();
    });
  });

  it("shows error on run failure", async () => {
    const agents = [{
      id: "a1", name: "Failbot", description: "will fail",
      schedule_type: "manual", cron_expression: null, status: "active",
      delivery_channel: "api", run_count: 0, error_count: 0,
      last_run_at: null, next_run_at: null, last_result: null,
      last_error: null, created_at: "2026-03-30T10:00:00Z",
    }];
    mockListAgents.mockResolvedValue(agents);
    mockRunAgent.mockRejectedValue(new Error("Run failed"));

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText(/Failbot/)).toBeTruthy();
    });

    await user.click(screen.getByText("Run"));

    await waitFor(() => {
      expect(screen.getByText("Run failed")).toBeTruthy();
    });
  });

  it("shows error on delete failure", async () => {
    const agents = [{
      id: "a1", name: "Undeletable", description: "can't delete",
      schedule_type: "manual", cron_expression: null, status: "active",
      delivery_channel: "api", run_count: 0, error_count: 0,
      last_run_at: null, next_run_at: null, last_result: null,
      last_error: null, created_at: "2026-03-30T10:00:00Z",
    }];
    mockListAgents.mockResolvedValue(agents);
    mockDeleteAgent.mockRejectedValue(new Error("Delete failed"));

    const user = userEvent.setup();
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText(/Undeletable/)).toBeTruthy();
    });

    await user.click(screen.getByText("Delete"));

    await waitFor(() => {
      expect(screen.getByText("Delete failed")).toBeTruthy();
    });
  });

  it("renders paused and error status icons", async () => {
    const agents = [
      {
        id: "a1", name: "Paused Agent", description: "paused",
        schedule_type: "manual", cron_expression: null, status: "paused",
        delivery_channel: "api", run_count: 0, error_count: 0,
        last_run_at: null, next_run_at: null, last_result: null,
        last_error: null, created_at: "2026-03-30T10:00:00Z",
      },
      {
        id: "a2", name: "Error Agent", description: "errored",
        schedule_type: "manual", cron_expression: null, status: "error",
        delivery_channel: "api", run_count: 1, error_count: 1,
        last_run_at: null, next_run_at: null, last_result: null,
        last_error: "Something broke",
        created_at: "2026-03-30T10:00:00Z",
      },
    ];
    mockListAgents.mockResolvedValue(agents);
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText(/Paused Agent/)).toBeTruthy();
      expect(screen.getByText(/Error Agent/)).toBeTruthy();
    });
    expect(screen.getByText(/Something broke/)).toBeTruthy();
  });

  it("shows error when initial list load fails", async () => {
    mockListAgents.mockRejectedValue(new Error("Network error"));
    render(<AgentsView />);

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeTruthy();
    });
  });
});
