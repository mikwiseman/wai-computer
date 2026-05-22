import type React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./dashboard/page";
import LoginPage from "./login/page";
import RegisterPage from "./register/page";
import AppMagicLinkPage from "./auth/app/page";
import ResetPasswordPage from "./auth/reset/page";
import VerifyMagicLinkPage from "./auth/verify/page";
import OnboardingPage from "./onboarding/page";
import SharedRecordingPage from "./share/[token]/page";
import Home from "./page";
import RuHome from "./ru/page";
import DictationBenchmarkPage from "./benchmarks/dictation/page";
import RuDictationBenchmarkPage from "./ru/benchmarks/dictation/page";
import BillingCancelPage from "./billing/cancel/page";
import BillingSuccessPage from "./billing/success/page";
import RuBillingCancelPage from "./ru/billing/cancel/page";
import RuBillingSuccessPage from "./ru/billing/success/page";
import RootLayout, { metadata, viewport } from "./layout";
import PrivacyPage from "./privacy/page";
import TermsPage from "./terms/page";
import RuPrivacyPage from "./ru/privacy/page";
import RuTermsPage from "./ru/terms/page";

const requestHeaderMock = vi.hoisted(() => ({
  acceptLanguage: null as string | null,
  referer: null as string | null,
}));
const mockReplace = vi.fn();
const authFormMock = vi.fn();
const dashboardClientMock = vi.fn();
const verifyClientMock = vi.fn();
const onboardingClientMock = vi.fn();
const sharedRecordingClientMock = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/",
}));

vi.mock("next/headers", () => ({
  headers: async () => ({
    get: (name: string) => {
      const key = name.toLowerCase();
      if (key === "accept-language") return requestHeaderMock.acceptLanguage;
      if (key === "referer") return requestHeaderMock.referer;
      return null;
    },
  }),
}));

vi.mock("next/font/google", () => ({
  Space_Grotesk: () => ({ variable: "font-space-grotesk" }),
}));

vi.mock("@/components/AuthForm", () => ({
  AuthForm: (props: unknown) => {
    authFormMock(props);
    return <div data-testid="auth-form-mock">Auth Form</div>;
  },
}));

vi.mock("@/components/DashboardClient", () => ({
  DashboardClient: (props: unknown) => {
    dashboardClientMock(props);
    return <div data-testid="dashboard-client-mock">Dashboard Client</div>;
  },
}));

vi.mock("@/components/VerifyMagicLinkClient", () => ({
  VerifyMagicLinkClient: ({ token, locale }: { token: string | null; locale?: string | null }) => {
    verifyClientMock(token, locale ?? null);
    return <div data-testid="verify-client-mock">{token ?? "null-token"}</div>;
  },
}));

vi.mock("@/components/OnboardingClient", () => ({
  OnboardingClient: () => {
    onboardingClientMock();
    return <div data-testid="onboarding-client-mock">Onboarding Client</div>;
  },
}));

vi.mock("@/components/SharedRecordingClient", () => ({
  SharedRecordingClient: ({ token }: { token: string }) => {
    sharedRecordingClientMock(token);
    return <div data-testid="shared-recording-client-mock">{token}</div>;
  },
}));

describe("app pages", () => {
  beforeEach(() => {
    mockReplace.mockClear();
    authFormMock.mockClear();
    dashboardClientMock.mockClear();
    verifyClientMock.mockClear();
    onboardingClientMock.mockClear();
    sharedRecordingClientMock.mockClear();
    requestHeaderMock.acceptLanguage = null;
    requestHeaderMock.referer = null;
    mockSearchParams = new URLSearchParams();
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

  it("renders login page and wires onSuccess to router", async () => {
    render(await LoginPage());
    expect(screen.getByTestId("auth-form-mock")).toBeInTheDocument();

    const call = authFormMock.mock.calls[0]?.[0] as {
      mode: string;
      initialLocale: string;
      onSuccess: () => void;
    };
    expect(call.mode).toBe("login");
    expect(call.initialLocale).toBe("en");
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("renders register page and wires onSuccess to router", async () => {
    render(await RegisterPage());
    expect(screen.getByTestId("auth-form-mock")).toBeInTheDocument();

    const call = authFormMock.mock.calls[0]?.[0] as {
      mode: string;
      initialLocale: string;
      onSuccess: () => void;
    };
    expect(call.mode).toBe("register");
    expect(call.initialLocale).toBe("en");
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("passes browser locale from request headers to auth pages", async () => {
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9,en-US;q=0.8";

    render(await LoginPage());
    render(await RegisterPage());

    const loginCall = authFormMock.mock.calls[0]?.[0] as { initialLocale: string };
    const registerCall = authFormMock.mock.calls[1]?.[0] as { initialLocale: string };
    expect(loginCall.initialLocale).toBe("ru");
    expect(registerCall.initialLocale).toBe("ru");
  });

  it("uses a safe returnTo target after login", async () => {
    mockSearchParams = new URLSearchParams({
      returnTo: "/api/mcp/oauth/consent?request=oauth-request",
    });
    render(await LoginPage());

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/api/mcp/oauth/consent?request=oauth-request");
  });

  it("rejects external returnTo targets after login", async () => {
    mockSearchParams = new URLSearchParams({ returnTo: "https://evil.example/callback" });
    render(await LoginPage());

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("renders dashboard wrapper", () => {
    render(<DashboardPage />);
    expect(screen.getByTestId("dashboard-client-mock")).toBeInTheDocument();
    expect(dashboardClientMock).toHaveBeenCalled();
  });

  it("renders onboarding wrapper", () => {
    render(<OnboardingPage />);
    expect(screen.getByTestId("onboarding-client-mock")).toBeInTheDocument();
    expect(onboardingClientMock).toHaveBeenCalled();
  });

  it("resolves verify token from searchParams", async () => {
    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token", locale: "ru" }) }));
    expect(screen.getByTestId("verify-client-mock")).toHaveTextContent("abc-token");

    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getAllByTestId("verify-client-mock")[1]).toHaveTextContent("null-token");
    expect(verifyClientMock).toHaveBeenCalledWith("abc-token", "ru");
    expect(verifyClientMock).toHaveBeenCalledWith(null, "en");
  });

  it("resolves app magic-link token and client from searchParams", async () => {
    render(await AppMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token", client: "macos" }) }));

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("Opening WaiComputer");
    expect(screen.getByTestId("open-app-link")).toHaveAttribute(
      "href",
      "waicomputer://auth/verify?token=abc-token",
    );
  });

  it("renders localized app-open and reset pages", async () => {
    render(
      await AppMagicLinkPage({
        searchParams: Promise.resolve({ token: "abc-token", client: "macos", locale: "ru" }),
      }),
    );
    expect(screen.getByRole("heading", { name: "Открыть приложение WaiComputer" })).toBeInTheDocument();
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=abc-token&locale=ru",
    );

    render(await ResetPasswordPage({ searchParams: Promise.resolve({ token: "reset-token", locale: "ru" }) }));
    expect(screen.getByRole("heading", { name: "Сброс пароля" })).toBeInTheDocument();
    expect(screen.getByTestId("reset-password-submit")).toHaveTextContent("Сбросить пароль");
  });

  it("falls back to browser Russian locale for app-open links without locale query", async () => {
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9,en-US;q=0.8";

    render(await AppMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token", client: "macos" }) }));

    expect(screen.getByRole("heading", { name: "Открыть приложение WaiComputer" })).toBeInTheDocument();
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=abc-token&locale=ru",
    );
  });

  it("passes shared recording token from route params", async () => {
    render(await SharedRecordingPage({ params: Promise.resolve({ token: "share-token" }) }));
    expect(screen.getByTestId("shared-recording-client-mock")).toHaveTextContent("share-token");
    expect(sharedRecordingClientMock).toHaveBeenCalledWith("share-token");
  });

  it("renders landing with download links and sign-in", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /AI second brain for everything you say/i,
      }),
    ).toBeInTheDocument();

    const macLink = screen.getByTestId("download-mac");
    expect(macLink).toHaveAttribute("href", "/releases/macos/WaiComputer-latest.dmg");
    expect(macLink).toHaveAttribute("download");
    expect(macLink).toHaveTextContent("macOS 14+");

    // Windows is live as of 0.1.0-beta (unsigned). Flip WINDOWS_AVAILABLE
    // back to false in page.tsx if the file is ever taken down.
    const winLink = screen.getByTestId("download-windows");
    expect(winLink).toHaveAttribute("href", "/releases/windows/WaiComputer-Setup.exe");
    expect(winLink).toHaveAttribute("download");
    expect(winLink).toHaveTextContent("Windows 10/11");

    const linuxLink = screen.getByTestId("download-linux");
    expect(linuxLink).toHaveAttribute("href", "/releases/linux/is.waiwai.computer.AppImage");
    expect(linuxLink).toHaveAttribute("download");
    expect(linuxLink).toHaveTextContent("AppImage");

    const iosLink = screen.getByTestId("download-ios");
    expect(iosLink).toHaveAttribute(
      "href",
      "https://testflight.apple.com/join/rtnJQzwk",
    );
    expect(iosLink).toHaveTextContent("TestFlight");
    expect(iosLink).not.toHaveAttribute("target");

    const androidLink = screen.getByTestId("download-android");
    expect(androidLink).toHaveAttribute(
      "href",
      "/releases/android/WaiComputer-latest.apk",
    );
    expect(androidLink).toHaveAttribute("download");
    expect(androidLink).toHaveTextContent("APK");
    expect(screen.getByRole("link", { name: "Benchmark" })).toHaveAttribute(
      "href",
      "/benchmarks/dictation",
    );
  });

  it("renders Russian landing with download links including Android", () => {
    render(<RuHome />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /AI second brain для всего/i,
      }),
    ).toBeInTheDocument();

    const macLink = screen.getByTestId("download-mac-ru");
    expect(macLink).toHaveAttribute("href", "/releases/macos/WaiComputer-ru-latest.dmg");
    expect(macLink).toHaveAttribute("download");
    expect(macLink).toHaveTextContent("Скачать для Mac");

    const linuxLink = screen.getByTestId("download-linux-ru");
    expect(linuxLink).toHaveAttribute("href", "/releases/linux/is.waiwai.computer.AppImage");
    expect(linuxLink).toHaveAttribute("download");
    expect(linuxLink).toHaveTextContent("AppImage");

    const iosLink = screen.getByTestId("download-ios-ru");
    expect(iosLink).toHaveAttribute(
      "href",
      "https://testflight.apple.com/join/rtnJQzwk",
    );
    expect(iosLink).toHaveTextContent("TestFlight");

    const androidLink = screen.getByTestId("download-android-ru");
    expect(androidLink).toHaveAttribute(
      "href",
      "/releases/android/WaiComputer-latest.apk",
    );
    expect(androidLink).toHaveAttribute("download");
    expect(androidLink).toHaveTextContent("APK");

    expect(screen.getByRole("link", { name: /войти/i })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(
      screen.getByRole("link", { name: /конфиденциальность/i }),
    ).toHaveAttribute("href", "/ru/privacy");
    expect(screen.getByRole("link", { name: "Бенчмарк" })).toHaveAttribute(
      "href",
      "/ru/benchmarks/dictation",
    );
  });

  it("renders dictation benchmark page", () => {
    render(<DictationBenchmarkPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /WaiComputer Dictation Arena/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Start dictation battle/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("WaiComputer Synthetic Dictation v1")).toBeInTheDocument();
    expect(screen.getAllByText("Soniox v4 Async").length).toBeGreaterThanOrEqual(1);
  });

  it("renders Russian dictation benchmark page", () => {
    render(<RuDictationBenchmarkPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /WaiComputer Арена диктовки/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Начать dictation battle/i })).toBeInTheDocument();
  });

  it("renders localized billing result pages", async () => {
    render(await BillingCancelPage());
    expect(screen.getByRole("heading", { level: 1, name: "Checkout canceled" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open billing" })).not.toBeInTheDocument();

    cleanup();
    render(await BillingSuccessPage());
    expect(screen.getByRole("heading", { level: 1, name: "Billing updated" })).toBeInTheDocument();

    cleanup();
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9,en;q=0.7";
    render(await BillingSuccessPage());
    expect(screen.getByRole("heading", { level: 1, name: "Оплата обновлена" })).toBeInTheDocument();

    cleanup();
    render(await BillingCancelPage({ searchParams: Promise.resolve({ provider: "tinkoff" }) }));
    expect(screen.getByRole("heading", { level: 1, name: "Оплата не прошла" })).toBeInTheDocument();
    expect(screen.getByText(/4242 4242 4242 4242/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Вернуться к подписке" })).not.toBeInTheDocument();

    cleanup();
    render(<RuBillingCancelPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Оплата не прошла" })).toBeInTheDocument();

    cleanup();
    render(<RuBillingSuccessPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Оплата обновлена" })).toBeInTheDocument();
  });

  it("renders first-party privacy and terms pages", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByText(/WaiComputer is operated by WaiWai/i)).toBeInTheDocument();

    render(<TermsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.getByText(/By creating an account/i)).toBeInTheDocument();

    render(<RuPrivacyPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Политика конфиденциальности" })).toBeInTheDocument();

    render(<RuTermsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Условия сервиса" })).toBeInTheDocument();
  });
});

describe("layout", () => {
  it("exports metadata and renders html/body structure", () => {
    expect(metadata.title).toBe("WaiComputer — AI second brain for voice");
    expect(metadata.description).toBe(
      "Record, transcribe, search, and ask anything across everything you've ever said.",
    );
    expect(viewport.themeColor).toEqual([
      { media: "(prefers-color-scheme: light)", color: "#f7f7f5" },
      { media: "(prefers-color-scheme: dark)", color: "#101214" },
    ]);

    const element = RootLayout({ children: <div data-testid="layout-child">Child</div> });
    expect(element.type).toBe("html");
    expect((element.props as { lang: string }).lang).toBe("en");

    const body = (element.props as { children: React.ReactElement }).children;
    expect(body.type).toBe("body");
    expect((body.props as { className: string }).className).toContain("font-space-grotesk");
  });
});
