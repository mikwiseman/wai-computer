import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentChat } from "./AgentChat";

vi.mock("@/lib/api", () => ({
  sendAgentMessage: vi.fn(),
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

const mockSendAgentMessage = vi.mocked(
  (await import("@/lib/api")).sendAgentMessage,
);

describe("AgentChat", () => {
  it("renders empty state with suggestions", () => {
    render(<AgentChat />);
    expect(screen.getByText("What can I help with?")).toBeTruthy();
    expect(screen.getByText("Find what Alex said about pricing")).toBeTruthy();
    expect(screen.getByText("Create a habit tracker")).toBeTruthy();
  });

  it("has an input field", () => {
    render(<AgentChat />);
    const input = screen.getByTestId("agent-chat-input");
    expect(input).toBeTruthy();
  });

  it("sends message and shows response", async () => {
    mockSendAgentMessage.mockResolvedValue({
      response: "Hello! I can help with that.",
      intent: "chat",
      model_used: "claude-haiku-4-5",
      session_id: "sess-1",
      tool_calls: 0,
      input_tokens: 50,
      output_tokens: 20,
    });

    const user = userEvent.setup();
    render(<AgentChat />);

    const input = screen.getByTestId("agent-chat-input");
    await user.type(input, "hello");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(
        screen.getByText("Hello! I can help with that."),
      ).toBeTruthy();
    });
    expect(mockSendAgentMessage).toHaveBeenCalledWith(
      "hello",
      undefined,
    );
  });

  it("clicking suggestion fills input", async () => {
    const user = userEvent.setup();
    render(<AgentChat />);

    await user.click(
      screen.getByText("Create a habit tracker"),
    );

    const input = screen.getByTestId(
      "agent-chat-input",
    ) as HTMLInputElement;
    expect(input.value).toBe("Create a habit tracker");
  });

  it("shows error on failure", async () => {
    mockSendAgentMessage.mockRejectedValue(
      new Error("Service unavailable"),
    );

    const user = userEvent.setup();
    render(<AgentChat />);

    const input = screen.getByTestId("agent-chat-input");
    await user.type(input, "hello");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(
        screen.getByText("Service unavailable"),
      ).toBeTruthy();
    });
  });

  it("disables input while loading", async () => {
    let resolveMessage: (value: unknown) => void;
    mockSendAgentMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveMessage = resolve;
      }),
    );

    const user = userEvent.setup();
    render(<AgentChat />);

    const input = screen.getByTestId(
      "agent-chat-input",
    ) as HTMLInputElement;
    await user.type(input, "hello");
    await user.keyboard("{Enter}");

    expect(input.disabled).toBe(true);
    expect(screen.getByText("Thinking...")).toBeTruthy();

    resolveMessage!({
      response: "Done",
      intent: "chat",
      model_used: "test",
      session_id: "s1",
      tool_calls: 0,
      input_tokens: 0,
      output_tokens: 0,
    });

    await waitFor(() => {
      expect(input.disabled).toBe(false);
    });
  });
});
