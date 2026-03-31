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
});
