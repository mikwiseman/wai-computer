import type React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./dashboard/page";
import LoginPage from "./login/page";
import RegisterPage from "./register/page";
import AppMagicLinkPage from "./auth/app/page";
import VerifyMagicLinkPage from "./auth/verify/page";
import OnboardingPage from "./onboarding/page";
import SharedRecordingPage from "./share/[token]/page";
import Home from "./page";
import RootLayout, { metadata } from "./layout";
import PrivacyPage from "./privacy/page";
import TermsPage from "./terms/page";

const mockReplace = vi.fn();
const authFormMock = vi.fn();
const dashboardClientMock = vi.fn();
const verifyClientMock = vi.fn();
const onboardingClientMock = vi.fn();
const appMagicLinkClientMock = vi.fn();
const sharedRecordingClientMock = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
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
  VerifyMagicLinkClient: ({ token }: { token: string | null }) => {
    verifyClientMock(token);
    return <div data-testid="verify-client-mock">{token ?? "null-token"}</div>;
  },
}));

vi.mock("@/components/OnboardingClient", () => ({
  OnboardingClient: () => {
    onboardingClientMock();
    return <div data-testid="onboarding-client-mock">Onboarding Client</div>;
  },
}));

vi.mock("@/components/OpenWaiComputerAppClient", () => ({
  normalizeWaiComputerAppClient: (client: string | null | undefined) => (
    client === "android" || client === "ios" || client === "macos" ? client : null
  ),
  OpenWaiComputerAppClient: ({ token, client }: { token: string | null; client: string | null }) => {
    appMagicLinkClientMock({ token, client });
    return <div data-testid="open-app-client-mock">{`${client}:${token ?? "null-token"}`}</div>;
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
    appMagicLinkClientMock.mockClear();
    sharedRecordingClientMock.mockClear();
    mockSearchParams = new URLSearchParams();
  });

  it("renders login page and wires onSuccess to router", () => {
    render(<LoginPage />);
    expect(screen.getByTestId("auth-form-mock")).toBeInTheDocument();

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    expect(call.mode).toBe("login");
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("renders register page and wires onSuccess to router", () => {
    render(<RegisterPage />);
    expect(screen.getByTestId("auth-form-mock")).toBeInTheDocument();

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    expect(call.mode).toBe("register");
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("uses a safe returnTo target after login", () => {
    mockSearchParams = new URLSearchParams({
      returnTo: "/api/mcp/oauth/consent?request=oauth-request",
    });
    render(<LoginPage />);

    const call = authFormMock.mock.calls[0]?.[0] as { mode: string; onSuccess: () => void };
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/api/mcp/oauth/consent?request=oauth-request");
  });

  it("rejects external returnTo targets after login", () => {
    mockSearchParams = new URLSearchParams({ returnTo: "https://evil.example/callback" });
    render(<LoginPage />);

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
    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token" }) }));
    expect(screen.getByTestId("verify-client-mock")).toHaveTextContent("abc-token");

    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getAllByTestId("verify-client-mock")[1]).toHaveTextContent("null-token");
    expect(verifyClientMock).toHaveBeenCalledWith(null);
  });

  it("resolves app magic-link token and client from searchParams", async () => {
    render(await AppMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token", client: "macos" }) }));

    expect(screen.getByTestId("open-app-client-mock")).toHaveTextContent("macos:abc-token");
    expect(appMagicLinkClientMock).toHaveBeenCalledWith({ token: "abc-token", client: "macos" });
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

    expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.getByRole("link", { name: /privacy/i })).toHaveAttribute(
      "href",
      "/privacy",
    );

    const icon = document.querySelector("img[alt='']");
    expect(icon).not.toBeNull();
  });

  it("renders first-party privacy and terms pages", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByText(/WaiComputer is operated by WaiWai/i)).toBeInTheDocument();

    render(<TermsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.getByText(/By using WaiComputer/i)).toBeInTheDocument();
  });
});

describe("layout", () => {
  it("exports metadata and renders html/body structure", () => {
    expect(metadata.title).toBe("WaiComputer — AI second brain for voice");
    expect(metadata.description).toBe(
      "Record, transcribe, search, and ask anything across everything you've ever said.",
    );

    const element = RootLayout({ children: <div data-testid="layout-child">Child</div> });
    expect(element.type).toBe("html");
    expect((element.props as { lang: string }).lang).toBe("en");

    const body = (element.props as { children: React.ReactElement }).children;
    expect(body.type).toBe("body");
    expect((body.props as { className: string }).className).toContain("font-space-grotesk");
  });
});
