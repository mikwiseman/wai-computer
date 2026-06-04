import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ServerDataSection } from "./ServerDataSection";

const mockGetSystemInfo = vi.fn();
const mockGetDataOwnershipMap = vi.fn();
const mockStartSelfHostProvision = vi.fn();

vi.mock("@/lib/api", () => ({
  getSystemInfo: (...args: unknown[]) => mockGetSystemInfo(...args),
  getDataOwnershipMap: (...args: unknown[]) => mockGetDataOwnershipMap(...args),
  startSelfHostProvision: (...args: unknown[]) => mockStartSelfHostProvision(...args),
}));

const systemInfo = {
  app_name: "WaiComputer",
  deployment_mode: "self_host",
  public_base_url: "https://demo.self.wai.computer",
  cloud_base_url: "https://wai.computer",
  mcp_url: "https://demo.self.wai.computer/mcp",
  git_sha: null,
  git_dirty: false,
  audio_retention_policy: "delete_after_processing",
  self_hosting_available: true,
  billing_mode: "self_host",
};

const dataOwnershipMap = {
  audio_retention_policy: "delete_after_processing",
  tables: [
    {
      name: "recordings",
      table: "recordings",
      classification: "owned_exportable",
      reason: "Recording metadata and lifecycle state.",
      contains_user_content: true,
      requires_reconnect: false,
    },
    {
      name: "mcp_connections",
      table: "mcp_connections",
      classification: "owned_exportable",
      reason: "MCP connection metadata moves, encrypted credentials reconnect.",
      contains_user_content: false,
      requires_reconnect: true,
    },
    {
      name: "mcp_oauth_tokens",
      table: "mcp_oauth_tokens",
      classification: "reconnect_required",
      reason: "MCP OAuth token hashes are server-bound and must be reissued.",
      contains_user_content: false,
      requires_reconnect: true,
    },
  ],
  artifacts: [
    {
      name: "document_uploads",
      classification: "owned_exportable",
      reason: "Original document uploads move with the user's data.",
      contains_user_content: true,
      requires_reconnect: false,
      path_hint: "${UPLOAD_STAGING_DIR}/items/<user_id>/*",
    },
    {
      name: "recording_audio_staging",
      classification: "self_host_local",
      reason: "Temporary audio upload input is deleted after processing.",
      contains_user_content: true,
      requires_reconnect: false,
      path_hint: "${UPLOAD_STAGING_DIR}/<user_id>/*",
    },
  ],
};

describe("ServerDataSection", () => {
  beforeEach(() => {
    mockGetSystemInfo.mockResolvedValue(systemInfo);
    mockGetDataOwnershipMap.mockResolvedValue(dataOwnershipMap);
    mockStartSelfHostProvision.mockResolvedValue({
      job_id: "selfhost_demo",
      status: "manual_review_required",
      hostname: "demo.self.wai.computer",
      vps_ip: "203.0.113.10",
      message: "Provisioning inputs are valid.",
      steps: [
        {
          id: "validate_inputs",
          label: "Validate server address and SSH access",
          status: "manual_review_required",
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    mockGetSystemInfo.mockReset();
    mockGetDataOwnershipMap.mockReset();
    mockStartSelfHostProvision.mockReset();
  });

  it("loads the active server and summarizes user-owned data", async () => {
    render(<ServerDataSection />);

    const section = await screen.findByTestId("server-data-section");
    expect(section.textContent).toContain("My server");
    expect(section.textContent).toContain("https://demo.self.wai.computer");
    expect(section.textContent).toContain("https://demo.self.wai.computer/mcp");
    expect(section.textContent).toContain("Owned exportable records");
    expect(section.textContent).toContain("Files and artifacts");
    expect(section.textContent).toContain("Needs reconnect");
    expect(section.textContent).toContain("2Needs reconnect");
  });

  it("submits a self-host provisioning preflight with a public SSH key", async () => {
    render(<ServerDataSection />);

    await screen.findByText("https://demo.self.wai.computer");
    expect(screen.queryByLabelText("Server address")).toBeNull();
    fireEvent.change(screen.getByLabelText("VPS IP address"), {
      target: { value: "203.0.113.10" },
    });
    fireEvent.change(screen.getByLabelText("SSH method"), {
      target: { value: "ssh_key" },
    });
    fireEvent.change(screen.getByLabelText("SSH public key"), {
      target: { value: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check setup" }));

    await waitFor(() => {
      expect(mockStartSelfHostProvision).toHaveBeenCalledWith({
        hostname: null,
        vps_ip: "203.0.113.10",
        ssh_username: "root",
        auth_method: "ssh_key",
        ssh_public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest demo",
        ssh_password: null,
      });
    });
    expect(await screen.findByTestId("server-provision-result")).toHaveTextContent(
      "manual_review_required",
    );
  });

  it("keeps the public domain optional behind an advanced section", async () => {
    render(<ServerDataSection />);

    await screen.findByText("https://demo.self.wai.computer");
    fireEvent.change(screen.getByLabelText("VPS IP address"), {
      target: { value: "203.0.113.10" },
    });
    fireEvent.change(screen.getByLabelText("Temporary password"), {
      target: { value: "bootstrap-password" },
    });
    fireEvent.click(screen.getByText("Optional public domain"));
    fireEvent.change(screen.getByLabelText("Public domain (optional)"), {
      target: { value: "demo.self.wai.computer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check setup" }));

    await waitFor(() => {
      expect(mockStartSelfHostProvision).toHaveBeenCalledWith({
        hostname: "demo.self.wai.computer",
        vps_ip: "203.0.113.10",
        ssh_username: "root",
        auth_method: "password",
        ssh_public_key: null,
        ssh_password: "bootstrap-password",
      });
    });
  });

  it("shows account actions instead of the provisioning form in public setup mode", async () => {
    render(<ServerDataSection provisioning="account_required" />);

    await screen.findByText("https://demo.self.wai.computer");
    expect(screen.queryByRole("button", { name: "Check setup" })).toBeNull();
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});
