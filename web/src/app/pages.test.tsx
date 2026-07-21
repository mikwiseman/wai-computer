import type React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
import RuPricingPage from "./ru/pricing/page";
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
const mockGetCurrentUser = vi.fn();
const authFormMock = vi.fn();
const dashboardClientMock = vi.fn();
const verifyClientMock = vi.fn();
const onboardingClientMock = vi.fn();
const sharedRecordingClientMock = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
}));

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
  SharedRecordingClient: ({
    token,
    locale,
  }: {
    token: string;
    locale?: string;
  }) => {
    sharedRecordingClientMock({ token, locale });
    return <div data-testid="shared-recording-client-mock">{token}</div>;
  },
}));

describe("app pages", () => {
  beforeEach(() => {
    mockReplace.mockClear();
    mockGetCurrentUser.mockReset();
    mockGetCurrentUser.mockRejectedValue(new Error("unauthenticated"));
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
    // Un-enrolled (or unknown) users land on onboarding after password login.
    call.onSuccess();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/onboarding"));

    mockReplace.mockClear();
    mockGetCurrentUser.mockResolvedValue({ has_enrolled_voice: true });
    call.onSuccess();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/dashboard"));
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
    // Fresh accounts always start at onboarding.
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/onboarding");
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
    mockGetCurrentUser.mockResolvedValue({ has_enrolled_voice: true });
    render(await LoginPage());

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    call.onSuccess();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/dashboard"));
    expect(mockReplace).not.toHaveBeenCalledWith(expect.stringContaining("evil.example"));
  });

  it("renders dashboard wrapper", () => {
    render(<DashboardPage />);
    expect(screen.getByTestId("dashboard-client-mock")).toBeInTheDocument();
    expect(dashboardClientMock).toHaveBeenCalled();
  });

  it("renders onboarding wrapper", async () => {
    render(await OnboardingPage());
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
    expect(screen.getByRole("heading", { name: "Открыть в WaiComputer" })).toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Открыть в WaiComputer" })).toBeInTheDocument();
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=abc-token&locale=ru",
    );
  });

  it("passes shared recording token from route params", async () => {
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9";
    render(await SharedRecordingPage({ params: Promise.resolve({ token: "share-token" }) }));
    expect(screen.getByTestId("shared-recording-client-mock")).toHaveTextContent("share-token");
    expect(sharedRecordingClientMock).toHaveBeenCalledWith({
      token: "share-token",
      locale: "ru",
    });
  });

  it("renders the focused English memory journey", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Build a second memory.",
      }),
    ).toBeInTheDocument();

    expect(screen.getByTestId("primary-cta")).toHaveAttribute("href", "/register");
    expect(screen.getByTestId("download-web")).toHaveAttribute("href", "/dashboard");

    const macLink = screen.getByTestId("download-mac");
    expect(macLink).toHaveAttribute(
      "href",
      "/releases/macos/WaiComputer-latest.dmg",
    );
    expect(macLink).toHaveAttribute("download");
    expect(macLink).toHaveTextContent("Mac");

    const iosLink = screen.getByTestId("download-ios");
    expect(iosLink).toHaveAttribute(
      "href",
      "https://testflight.apple.com/join/rtnJQzwk",
    );
    expect(iosLink).toHaveTextContent("iPhone");
    expect(iosLink).not.toHaveAttribute("target");

    expect(screen.getByRole("heading", { level: 3, name: "Said" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Understood" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Found" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Every memory, in one Inbox." }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("WaiComputer recording summary and transcript")).toBeInTheDocument();
    expect(screen.getByAltText("WaiComputer memory library")).toBeInTheDocument();
    expect(screen.getByText("Recording starts only when you tell it to.")).toBeInTheDocument();
    expect(screen.queryByText(/What does WaiComputer record\?/i)).not.toBeInTheDocument();
    expect(screen.queryByText("3,000 transcribed words per week")).not.toBeInTheDocument();
  });

  it("renders the focused Russian memory journey and payment details", () => {
    render(<RuHome />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Не держите всё в голове.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Записывайте встречи и голосовые заметки. WaiComputer расшифрует речь, выделит главное и поможет быстро найти нужное.",
      ),
    ).toBeInTheDocument();

    expect(screen.getByTestId("primary-cta-ru")).toHaveAttribute("href", "/register");

    const macLink = screen.getByTestId("download-mac-ru");
    expect(macLink).toHaveAttribute(
      "href",
      "/releases/macos/WaiComputer-ru-latest.dmg",
    );
    expect(macLink).toHaveAttribute("download");
    expect(macLink).toHaveTextContent("Mac");

    const webLink = screen.getByTestId("download-web-ru");
    expect(webLink).toHaveAttribute("href", "/dashboard");
    expect(webLink).toHaveTextContent("Открыть в браузере");

    const iosLink = screen.getByTestId("download-ios-ru");
    expect(iosLink).toHaveAttribute(
      "href",
      "https://testflight.apple.com/join/rtnJQzwk",
    );
    expect(iosLink).toHaveTextContent("iPhone");

    expect(screen.getByTestId("platform-web-ru")).toHaveAttribute("href", "/dashboard");
    expect(screen.getByTestId("platform-web-ru")).toHaveTextContent("Браузер");

    expect(screen.getByRole("link", { name: /войти/i })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(
      screen.getByRole("link", { name: "Конфиденциальность" }),
    ).toHaveAttribute("href", "/ru/privacy");
    expect(screen.getByRole("group", { name: "Язык" })).toBeInTheDocument();
    expect(screen.getByText("Как работает WaiComputer")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Запишите один раз. Найдите в любой момент." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Запись" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Главное" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Поиск" })).toBeInTheDocument();
    expect(
      screen.getByText("Получите расшифровку, краткий итог и список задач."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Откройте запись — сразу увидите главное." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Запись, расшифровка, краткий итог и задачи — в одном окне. Все записи собраны в общей библиотеке.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByAltText("Краткий итог и расшифровка в WaiComputer")).toBeInTheDocument();
    expect(screen.getByAltText("Библиотека записей WaiComputer")).toBeInTheDocument();
    expect(
      screen.getByText("Без фоновой записи — вы сами решаете, когда начать."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Начните с первой записи." }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/саммари|Инбокс|Нативно|Бенчмарк/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Оплата и документы" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("МИР")).toBeInTheDocument();
    expect(screen.getByAltText("Visa")).toBeInTheDocument();
    expect(screen.getByAltText("Mastercard")).toBeInTheDocument();
    expect(screen.getByAltText("Т-Банк T-Pay")).toBeInTheDocument();
    expect(screen.getByText("tbank.ru")).toBeInTheDocument();
    expect(screen.getByText(/Оплатить Pro в рублях можно через Т-Банк/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Правила оплаты, отмены подписки, возврата и рассмотрения претензий/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Т-Банк/i })).toHaveAttribute(
      "href",
      "https://www.tbank.ru/",
    );
    expect(screen.getByText(/ООО "ВАЙВАЙ"/i)).toBeInTheDocument();
    expect(screen.getByText("9714075304")).toBeInTheDocument();
    expect(screen.getByText(/ул\. Большая Садовая, 5\/1/i)).toBeInTheDocument();

    expect(screen.queryByText(/Что WaiComputer записывает\?/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/3 000 слов в неделю/i)).not.toBeInTheDocument();
  });

  it("renders Russian pricing with T-Bank payment compliance details", () => {
    render(<RuPricingPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Простые цены." })).toBeInTheDocument();
    expect(screen.getByText("RUB через Т-Банк")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Оплата в рублях" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/цифровая услуга/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/доступ к Pro открывается сразу после оплаты/i)).toBeInTheDocument();
    expect(screen.getAllByText(/возврат/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("link", { name: /tbank\.ru/i })).toHaveAttribute(
      "href",
      "https://www.tbank.ru/",
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
      screen.getByRole("button", { name: /Start recording/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("WaiComputer Active STT Stack")).toBeInTheDocument();
    expect(screen.getAllByText("ElevenLabs Scribe v2").length).toBeGreaterThanOrEqual(1);
  });

  it("renders Russian dictation benchmark page", () => {
    render(<RuDictationBenchmarkPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /WaiComputer Арена диктовки/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Начать запись/i })).toBeInTheDocument();
  });

  it("renders localized billing result pages", async () => {
    render(await BillingCancelPage());
    expect(screen.getByRole("heading", { level: 1, name: "Checkout canceled" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open billing" })).not.toBeInTheDocument();

    cleanup();
    render(await BillingSuccessPage());
    expect(screen.getByRole("heading", { level: 1, name: "You're all set" })).toBeInTheDocument();

    cleanup();
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9,en;q=0.7";
    render(await BillingSuccessPage());
    expect(screen.getByRole("heading", { level: 1, name: "Готово" })).toBeInTheDocument();

    cleanup();
    render(await BillingCancelPage({ searchParams: Promise.resolve({ provider: "tinkoff" }) }));
    expect(screen.getByRole("heading", { level: 1, name: "Оплата отменена" })).toBeInTheDocument();
    expect(screen.getByText(/деньги не списаны/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Вернуться к подписке" })).not.toBeInTheDocument();

    cleanup();
    render(<RuBillingCancelPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Оплата отменена" })).toBeInTheDocument();

    cleanup();
    render(<RuBillingSuccessPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Готово" })).toBeInTheDocument();
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
    expect(screen.getByText(/Безопасная передача платежных данных/i)).toBeInTheDocument();
    expect(screen.getByText(/не хранит номера банковских карт/i)).toBeInTheDocument();

    render(<RuTermsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Условия сервиса и публичная оферта" })).toBeInTheDocument();
    expect(screen.getByText(/Возврат и отмена/i)).toBeInTheDocument();
    expect(screen.getByText(/ООО "ВАЙВАЙ"/i)).toBeInTheDocument();
    expect(screen.getByText(/ИНН: 9714075304/i)).toBeInTheDocument();
  });
});

describe("layout", () => {
  it("exports metadata and renders html/body structure", async () => {
    expect(metadata.title).toBe("WaiComputer — AI second brain for voice");
    expect(metadata.description).toBe(
      "Save the meetings and voice notes you choose, then transcribe, search, and ask Wai about them.",
    );
    expect(viewport.themeColor).toEqual([
      { media: "(prefers-color-scheme: light)", color: "#f5f4f0" },
      { media: "(prefers-color-scheme: dark)", color: "#111311" },
    ]);

    requestHeaderMock.acceptLanguage = null;
    const element = await RootLayout({ children: <div data-testid="layout-child">Child</div> });
    expect(element.type).toBe("html");
    expect((element.props as { lang: string }).lang).toBe("en");

    const body = (element.props as { children: React.ReactElement }).children;
    expect(body.type).toBe("body");
    expect((body.props as { children: React.ReactNode }).children).toBeTruthy();
  });

  it("renders <html lang='ru'> when accept-language prefers Russian", async () => {
    requestHeaderMock.acceptLanguage = "ru-RU,ru;q=0.9,en-US;q=0.8";
    const element = await RootLayout({ children: <div /> });
    expect((element.props as { lang: string }).lang).toBe("ru");
  });
});
