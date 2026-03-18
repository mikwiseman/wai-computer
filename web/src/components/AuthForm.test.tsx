import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { AuthForm } from "./AuthForm";

const mockLogin = vi.fn();
const mockRegister = vi.fn();
const mockRequestMagicLink = vi.fn();

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  login: (...args: unknown[]) => mockLogin(...args),
  register: (...args: unknown[]) => mockRegister(...args),
  requestMagicLink: (...args: unknown[]) => mockRequestMagicLink(...args),
}));

describe("AuthForm", () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockRegister.mockReset();
    mockRequestMagicLink.mockReset();
  });

  it("submits login mode and calls onSuccess", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockLogin.mockResolvedValue({ access_token: "token", token_type: "bearer" });

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "login@example.com");
    await user.type(screen.getByTestId("auth-password"), "password123");
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("login@example.com", "password123");
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Need an account?" })).toHaveAttribute("href", "/register");
  });

  it("submits register mode and calls onSuccess", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockRegister.mockResolvedValue({ access_token: "token", token_type: "bearer" });

    render(<AuthForm mode="register" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "register@example.com");
    await user.type(screen.getByTestId("auth-password"), "password123");
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith("register@example.com", "password123");
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Have an account?" })).toHaveAttribute("href", "/login");
  });

  it("shows error messages for ApiError and Error submissions", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();

    mockLogin.mockRejectedValueOnce(new ApiError(401, "Invalid credentials"));
    mockLogin.mockRejectedValueOnce(new Error("Boom"));

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "error@example.com");
    await user.type(screen.getByTestId("auth-password"), "password123");
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("auth-message")).toHaveTextContent("Invalid credentials");
    });
    expect(onSuccess).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("auth-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("auth-message")).toHaveTextContent("Boom");
    });
  });

  it("handles magic link button states and unknown errors", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockResolvedValueOnce({ message: "Magic link sent" });
    mockRequestMagicLink.mockRejectedValueOnce("not-an-error-object");

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    const magicButton = screen.getByTestId("magic-link-button");
    expect(magicButton).toBeDisabled();

    await user.type(screen.getByTestId("auth-email"), "magic@example.com");
    expect(magicButton).not.toBeDisabled();

    await user.click(magicButton);
    await waitFor(() => {
      expect(screen.getByTestId("auth-message")).toHaveTextContent("Magic link sent");
    });

    await user.click(magicButton);
    await waitFor(() => {
      expect(screen.getByTestId("auth-message")).toHaveTextContent("Unexpected error");
    });
  });

  it("renders login mode heading and register mode heading correctly", () => {
    const { unmount } = render(<AuthForm mode="login" onSuccess={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign In");
    expect(screen.getByTestId("auth-submit")).toHaveTextContent("Sign In");
    expect(screen.getByRole("link", { name: "Need an account?" })).toHaveAttribute("href", "/register");
    unmount();

    render(<AuthForm mode="register" onSuccess={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Create Account");
    expect(screen.getByTestId("auth-submit")).toHaveTextContent("Create Account");
    expect(screen.getByRole("link", { name: "Have an account?" })).toHaveAttribute("href", "/login");
  });

  it("always renders both email and password fields regardless of mode", () => {
    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    const emailInput = screen.getByTestId("auth-email");
    const passwordInput = screen.getByTestId("auth-password");

    expect(emailInput).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("type", "email");
    expect(emailInput).toBeRequired();

    expect(passwordInput).toBeInTheDocument();
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toBeRequired();
  });

  it("shows loading text on submit button while request is pending", async () => {
    const user = userEvent.setup();
    let resolveLogin: (value: unknown) => void;
    mockLogin.mockImplementation(
      () => new Promise((resolve) => { resolveLogin = resolve; }),
    );

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await user.type(screen.getByTestId("auth-email"), "load@example.com");
    await user.type(screen.getByTestId("auth-password"), "password123");

    const submitButton = screen.getByTestId("auth-submit");
    expect(submitButton).toHaveTextContent("Sign In");
    expect(submitButton).not.toBeDisabled();

    await user.click(submitButton);

    await waitFor(() => {
      expect(submitButton).toHaveTextContent("Please wait...");
      expect(submitButton).toBeDisabled();
    });

    resolveLogin!({ access_token: "t", token_type: "bearer" });

    await waitFor(() => {
      expect(submitButton).toHaveTextContent("Sign In");
      expect(submitButton).not.toBeDisabled();
    });
  });

  it("disables magic link button when email field is empty", () => {
    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    const magicButton = screen.getByTestId("magic-link-button");
    expect(magicButton).toBeDisabled();

    const emailInput = screen.getByTestId("auth-email");
    expect(emailInput).toHaveValue("");
  });
});
