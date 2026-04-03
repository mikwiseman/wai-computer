import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppsView } from "./AppsView";

vi.mock("@/lib/api", () => ({
  listApps: vi.fn(),
  createAppItem: vi.fn(),
  deleteApp: vi.fn(),
  deleteAppItem: vi.fn(),
  getApp: vi.fn(),
  listAppItems: vi.fn(),
  listAppDeployments: vi.fn(),
  publishApp: vi.fn(),
  rollbackApp: vi.fn(),
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

const { listApps, listAppItems, listAppDeployments, publishApp, rollbackApp } = await import("@/lib/api");
const mockListApps = vi.mocked(listApps);
const mockListAppItems = vi.mocked(listAppItems);
const mockListAppDeployments = vi.mocked(listAppDeployments);
const mockPublishApp = vi.mocked(publishApp);
const mockRollbackApp = vi.mocked(rollbackApp);

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
        description: "Tracks habits",
        icon: "✅",
        template: "checklist",
        schema_def: null,
        app_url: null,
        settings: null,
        status: "draft",
        visibility: "private",
        published_at: null,
        last_used_at: null,
        sort_order: 0,
        item_count: 5,
        created_at: "2026-03-30T10:00:00Z",
      },
      {
        id: "app-2",
        name: "expenses",
        display_name: "Expenses",
        description: null,
        icon: "💰",
        template: "logger",
        schema_def: null,
        app_url: null,
        settings: null,
        status: "live",
        visibility: "public",
        published_at: "2026-03-31T10:00:00Z",
        last_used_at: "2026-03-31T12:00:00Z",
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
        description: "Tracks habits",
        icon: "✅",
        template: null,
        schema_def: null,
        app_url: null,
        settings: null,
        status: "draft",
        visibility: "private",
        published_at: null,
        last_used_at: null,
        sort_order: 0,
        item_count: 1,
        created_at: "2026-03-30T10:00:00Z",
      },
    ]);
    mockListAppDeployments.mockResolvedValue([]);
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
      expect(mockListAppDeployments).toHaveBeenCalledWith("app-1");
    });
  });

  it("publishes an app from detail view", async () => {
    mockListApps.mockResolvedValue([
      {
        id: "app-1",
        name: "habits",
        display_name: "Habit Tracker",
        description: "Tracks habits",
        icon: "✅",
        template: null,
        schema_def: null,
        app_url: "https://habits.wai.computer",
        settings: null,
        status: "draft",
        visibility: "public",
        published_at: null,
        last_used_at: null,
        sort_order: 0,
        item_count: 1,
        created_at: "2026-03-30T10:00:00Z",
      },
    ]);
    mockListAppItems.mockResolvedValue([]);
    mockListAppDeployments.mockResolvedValue([]);
    mockPublishApp.mockResolvedValue({
      id: "app-1",
      name: "habits",
      display_name: "Habit Tracker",
      description: "Tracks habits",
      icon: "✅",
      template: null,
      schema_def: null,
      app_url: "https://habits.wai.computer",
      settings: null,
      status: "live",
      visibility: "public",
      published_at: "2026-04-01T12:00:00Z",
      last_used_at: "2026-04-01T12:00:00Z",
      sort_order: 0,
      item_count: 1,
      created_at: "2026-03-30T10:00:00Z",
    });

    const user = userEvent.setup();
    render(<AppsView />);

    await waitFor(() => {
      expect(screen.getByText("Habit Tracker")).toBeTruthy();
    });

    await user.click(screen.getByText("Habit Tracker"));
    await user.click(await screen.findByText("Publish"));

    await waitFor(() => {
      expect(mockPublishApp).toHaveBeenCalledWith("app-1", {
        visibility: "public",
        app_url: "https://habits.wai.computer",
      });
      expect(mockListAppDeployments).toHaveBeenCalledWith("app-1");
    });
  });

  it("shows deployment history and rolls back an older deployment", async () => {
    mockListApps.mockResolvedValue([
      {
        id: "app-1",
        name: "habits",
        display_name: "Habit Tracker",
        description: "Tracks habits",
        icon: "✅",
        template: null,
        schema_def: null,
        app_url: "https://habits.wai.computer",
        settings: null,
        status: "live",
        visibility: "public",
        published_at: "2026-04-01T10:00:00Z",
        last_used_at: "2026-04-01T12:00:00Z",
        sort_order: 0,
        item_count: 1,
        created_at: "2026-03-30T10:00:00Z",
      },
    ]);
    mockListAppItems.mockResolvedValue([]);
    mockListAppDeployments.mockResolvedValue([
      {
        id: "dep-new",
        source_deployment_id: null,
        deployment_mode: "production",
        deployment_target: "cloudflare-pages",
        status: "succeeded",
        generated_slug: "habits",
        bundle_cache_key: "site:habits:v:new",
        cloudflare_project_name: "wai-site-habits",
        deployment_url: "https://wai-site-habits-abc.pages.dev",
        alias_url: "https://preview-habits.wai-site-habits.pages.dev",
        live_url: "https://habits.wai.computer",
        bundle_kind: "vite-react-site",
        framework: "react-vite",
        generation_provider: "claude-code",
        build_output_dir: "dist",
        build_command: "npm run build",
        created_at: "2026-04-01T12:00:00Z",
      },
      {
        id: "dep-old",
        source_deployment_id: null,
        deployment_mode: "preview",
        deployment_target: "cloudflare-pages",
        status: "succeeded",
        generated_slug: "habits",
        bundle_cache_key: "site:habits:v:old",
        cloudflare_project_name: "wai-site-habits",
        deployment_url: "https://wai-site-habits-old.pages.dev",
        alias_url: "https://preview-habits-old.pages.dev",
        live_url: null,
        bundle_kind: "vite-react-site",
        framework: "react-vite",
        generation_provider: "claude-code",
        build_output_dir: "dist",
        build_command: "npm run build",
        created_at: "2026-03-31T12:00:00Z",
      },
    ]);
    mockRollbackApp.mockResolvedValue({
      id: "app-1",
      name: "habits",
      display_name: "Habit Tracker",
      description: "Tracks habits",
      icon: "✅",
      template: null,
      schema_def: null,
      app_url: "https://habits.wai.computer",
      settings: null,
      status: "live",
      visibility: "public",
      published_at: "2026-04-01T12:30:00Z",
      last_used_at: "2026-04-01T12:30:00Z",
      sort_order: 0,
      item_count: 1,
      created_at: "2026-03-30T10:00:00Z",
    });

    const user = userEvent.setup();
    render(<AppsView />);

    await waitFor(() => {
      expect(screen.getByText("Habit Tracker")).toBeTruthy();
    });

    await user.click(screen.getByText("Habit Tracker"));

    await waitFor(() => {
      expect(screen.getByText("Deployments")).toBeTruthy();
      expect(screen.getByText("Live deployment")).toBeTruthy();
      expect(screen.getByText("Preview deployment")).toBeTruthy();
    });

    const previewLinks = screen.getAllByRole("link", { name: "Preview ↗" });
    expect(previewLinks).toHaveLength(2);
    expect(previewLinks[0]).toHaveAttribute("href", "https://preview-habits.wai-site-habits.pages.dev");
    expect(previewLinks[1]).toHaveAttribute("href", "https://preview-habits-old.pages.dev");
    expect(screen.getByRole("link", { name: "Live ↗" })).toHaveAttribute("href", "https://habits.wai.computer");
    const deploymentLinks = screen.getAllByRole("link", { name: "Deployment ↗" });
    expect(deploymentLinks).toHaveLength(2);
    expect(deploymentLinks[0]).toHaveAttribute("href", "https://wai-site-habits-abc.pages.dev");
    expect(deploymentLinks[1]).toHaveAttribute("href", "https://wai-site-habits-old.pages.dev");

    await user.click(screen.getAllByText("Roll back")[0]);

    await waitFor(() => {
      expect(mockRollbackApp).toHaveBeenCalledWith("app-1", {
        deployment_id: "dep-old",
        visibility: "public",
      });
    });
  });
});
