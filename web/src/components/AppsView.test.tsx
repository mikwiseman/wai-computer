import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppsView } from "./AppsView";

vi.mock("@/lib/api", () => ({
  listApps: vi.fn(),
  createAppItem: vi.fn(),
  deleteApp: vi.fn(),
  deleteAppItem: vi.fn(),
  listAppItems: vi.fn(),
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

const { listApps, listAppItems, deleteApp } = await import("@/lib/api");
const mockListApps = vi.mocked(listApps);
const mockListAppItems = vi.mocked(listAppItems);
const mockDeleteApp = vi.mocked(deleteApp);

describe("AppsView", () => {
  it("renders empty state", async () => {
    mockListApps.mockResolvedValue([]);
    render(<AppsView />);
    await waitFor(() => {
      expect(screen.getByText(/No apps yet/)).toBeTruthy();
    });
  });

  it("renders app grid", async () => {
    mockListApps.mockResolvedValue([
      {
        id: "app-1",
        name: "habits",
        display_name: "Habit Tracker",
        icon: "✅",
        template: "checklist",
        schema_def: null,
        app_url: null,
        settings: null,
        sort_order: 0,
        item_count: 5,
        created_at: "2026-03-30T10:00:00Z",
      },
      {
        id: "app-2",
        name: "expenses",
        display_name: "Expenses",
        icon: "💰",
        template: "logger",
        schema_def: null,
        app_url: null,
        settings: null,
        sort_order: 1,
        item_count: 12,
        created_at: "2026-03-29T10:00:00Z",
      },
    ]);
    render(<AppsView />);
    await waitFor(() => {
      expect(screen.getByText("Habit Tracker")).toBeTruthy();
      expect(screen.getByText("Expenses")).toBeTruthy();
    });
    expect(screen.getByText("5 items")).toBeTruthy();
    expect(screen.getByText("12 items")).toBeTruthy();
  });

  it("navigates to app detail on click", async () => {
    mockListApps.mockResolvedValue([
      {
        id: "app-1",
        name: "habits",
        display_name: "Habit Tracker",
        icon: "✅",
        template: null,
        schema_def: null,
        app_url: null,
        settings: null,
        sort_order: 0,
        item_count: 1,
        created_at: "2026-03-30T10:00:00Z",
      },
    ]);
    mockListAppItems.mockResolvedValue([
      {
        id: "item-1",
        data: { habit: "meditation", completed: true },
        created_at: "2026-03-30T08:00:00Z",
        updated_at: "2026-03-30T08:00:00Z",
      },
    ]);

    const user = userEvent.setup();
    render(<AppsView />);

    await waitFor(() => {
      expect(screen.getByText("Habit Tracker")).toBeTruthy();
    });

    await user.click(screen.getByText("Habit Tracker"));

    await waitFor(() => {
      expect(mockListAppItems).toHaveBeenCalledWith("app-1");
    });
  });
});
