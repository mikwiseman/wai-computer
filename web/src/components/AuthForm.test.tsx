import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { AuthForm } from "./AuthForm";

const mockLogin = vi.fn();
const mockRegister = vi.fn();
const mockRequestMagicLink = vi.fn();
const mockRequestPasswordReset = vi.fn();

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  login: (...args: unknown[]) => mockLogin(...args),
  register: (...args: unknown[]) => mockRegister(...args),
  requestMagicLink: (...args: unknown[]) => mockRequestMagicLink(...args),
  requestPasswordReset: (...args: unknown[]) => mockRequestPasswordReset(...args),
}));

describe("AuthForm", () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockRegister.mockReset();
    mockRequestMagicLink.mockReset();
    mockRequestPasswordReset.mockReset();
    setNavigatorLanguages(["en-US"]);
  });

  function setNavigatorLanguages(languages: string[], language = languages[0] ?? "en-US") {
    Object.defineProperty(window.navigator, "languages", {
      configurable: true,
      value: languages,
    });
    Object.defineProperty(window.navigator, "language", {
      configurable: true,
      value: language,
    });
  }

  it("uses magic link as the primary login flow", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockRequestMagicLink.mockResolvedValue({ message: "Magic link sent" });

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    expect(screen.queryByTestId("auth-password")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign in");

    await user.type(screen.getByTestId("auth-email"), "login@example.com");
    await user.click(screen.getByTestId("magic-link-button"));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("login@example.com", {
        locale: "en",
        region: "global",
      });
    });
    expect(mockLogin).not.toHaveBeenCalled();
    expect(mockRegister).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByTestId("auth-message")).toHaveTextContent("Magic link sent");
    expect(screen.getByRole("link", { name: "Need an account?" })).toHaveAttribute("href", "/register");
  });

  it("uses magic link as the primary register flow for new emails", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockRequestMagicLink.mockResolvedValue({ message: "Magic link sent" });

    render(<AuthForm mode="register" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "register@example.com");
    expect(screen.getByTestId("magic-link-button")).toBeDisabled();
    await user.click(screen.getByTestId("legal-consent-checkbox"));
    await user.click(screen.getByTestId("magic-link-button"));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("register@example.com", {
        locale: "en",
        region: "global",
        acceptedLegalTerms: true,
      });
    });
    expect(mockRegister).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Have an account?" })).toHaveAttribute("href", "/login");
  });

  it("shows error messages for ApiError and Error submissions", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();

    mockLogin.mockRejectedValueOnce(new ApiError(401, "Invalid credentials"));
    mockLogin.mockRejectedValueOnce(new Error("Boom"));

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "error@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
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
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign in");
    expect(screen.getByTestId("magic-link-button")).toHaveTextContent("Email me a sign-in link");
    expect(screen.getByRole("link", { name: "Need an account?" })).toHaveAttribute("href", "/register");
    unmount();

    render(<AuthForm mode="register" onSuccess={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Create account");
    expect(screen.getByTestId("magic-link-button")).toHaveTextContent("Email me a sign-in link");
    expect(screen.getByTestId("legal-consent-checkbox")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
    expect(screen.getByRole("link", { name: "Have an account?" })).toHaveAttribute("href", "/login");
  });

  it("uses browser Russian locale when no server locale is provided", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockResolvedValue({ message: "Ссылка отправлена" });
    setNavigatorLanguages(["ru-RU", "en-US"]);

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Войти");
    });
    expect(screen.getByTestId("magic-link-button")).toHaveTextContent("Отправить ссылку для входа");
    expect(screen.queryByText(/Magic Link|Register|Login/i)).not.toBeInTheDocument();

    await user.type(screen.getByTestId("auth-email"), "ru-login@example.com");
    await user.click(screen.getByTestId("magic-link-button"));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("ru-login@example.com", {
        locale: "ru",
        region: "ru",
      });
    });
  });

  it("passes legal acceptance when creating password accounts", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockRegister.mockResolvedValue({ access_token: "token", token_type: "bearer" });

    render(<AuthForm mode="register" initialLocale="ru" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "register-password@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    await user.type(screen.getByTestId("auth-password"), "password123");
    expect(screen.getByTestId("auth-submit")).toBeDisabled();
    expect(screen.getByRole("link", { name: "Условия сервиса" })).toHaveAttribute("href", "/ru/terms");
    expect(screen.getByRole("link", { name: "Политика конфиденциальности" })).toHaveAttribute("href", "/ru/privacy");

    await user.click(screen.getByTestId("legal-consent-checkbox"));
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith("register-password@example.com", "password123", {
        locale: "ru",
        region: "ru",
        acceptedLegalTerms: true,
      });
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("keeps password login as an explicit secondary mode", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockLogin.mockResolvedValue({ access_token: "token", token_type: "bearer" });

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    const emailInput = screen.getByTestId("auth-email");
    expect(emailInput).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("type", "email");
    expect(emailInput).toBeRequired();
    expect(screen.queryByTestId("auth-password")).not.toBeInTheDocument();

    await user.type(emailInput, "login@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    const passwordInput = screen.getByTestId("auth-password");
    expect(passwordInput).toBeInTheDocument();
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toBeRequired();

    await user.type(passwordInput, "password123");
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("login@example.com", "password123", {
        locale: "en",
        region: "global",
      });
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("shows loading text on submit button while request is pending", async () => {
    const user = userEvent.setup();
    let resolveLogin: (value: unknown) => void;
    mockLogin.mockImplementation(
      () => new Promise((resolve) => { resolveLogin = resolve; }),
    );

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await user.type(screen.getByTestId("auth-email"), "load@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    await user.type(screen.getByTestId("auth-password"), "password123");

    const submitButton = screen.getByTestId("auth-submit");
    expect(submitButton).toHaveTextContent("Sign in with password");
    expect(submitButton).not.toBeDisabled();

    await user.click(submitButton);

    await waitFor(() => {
      expect(submitButton).toHaveTextContent("Please wait...");
      expect(submitButton).toBeDisabled();
    });

    resolveLogin!({ access_token: "t", token_type: "bearer" });

    await waitFor(() => {
      expect(submitButton).toHaveTextContent("Sign in with password");
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

  it("uses Russian copy and locale when the browser language is Russian", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockResolvedValue({ message: "Мы отправили ссылку для входа на твою почту." });

    render(<AuthForm mode="login" initialLocale="ru" onSuccess={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Войти");
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByTestId("magic-link-button")).toHaveTextContent("Отправить ссылку для входа");

    await user.type(screen.getByTestId("auth-email"), "ru@example.com");
    await user.click(screen.getByTestId("magic-link-button"));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("ru@example.com", {
        locale: "ru",
        region: "ru",
      });
    });
  });

  it("updates to Russian browser locale after mount when no server locale is provided", async () => {
    setNavigatorLanguages(["ru-RU", "en-US"]);

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Войти");
    });
    expect(screen.getByTestId("magic-link-button")).toHaveTextContent("Отправить ссылку для входа");
  });

  it("shows forgot-password request flow from password login without enumerating users", async () => {
    const user = userEvent.setup();
    mockRequestPasswordReset.mockResolvedValue({
      message: "A reset link was sent to this existing account.",
    });

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await user.type(screen.getByTestId("auth-email"), "missing@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    await user.click(screen.getByTestId("forgot-password-button"));

    expect(screen.getByTestId("forgot-password-panel")).toBeInTheDocument();

    await user.click(screen.getByTestId("forgot-password-submit"));

    await waitFor(() => {
      expect(mockRequestPasswordReset).toHaveBeenCalledWith("missing@example.com", "en");
    });
    expect(screen.getByTestId("auth-message")).toHaveTextContent(
      "If this email is registered, we sent a password reset link.",
    );
    expect(screen.getByTestId("auth-message")).not.toHaveTextContent("existing account");
  });

  it("uses Russian copy for forgot-password request flow", async () => {
    const user = userEvent.setup();
    setNavigatorLanguages(["ru"]);
    mockRequestPasswordReset.mockResolvedValue({ message: "Подробный ответ сервера" });

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    await user.type(screen.getByTestId("auth-email"), "ru-reset@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    await user.click(screen.getByTestId("forgot-password-button"));
    await user.click(screen.getByTestId("forgot-password-submit"));

    await waitFor(() => {
      expect(mockRequestPasswordReset).toHaveBeenCalledWith("ru-reset@example.com", "ru");
    });
    expect(screen.getByTestId("auth-message")).toHaveTextContent(
      "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля.",
    );
    expect(screen.getByTestId("auth-message")).not.toHaveTextContent("Подробный ответ сервера");
  });
});
