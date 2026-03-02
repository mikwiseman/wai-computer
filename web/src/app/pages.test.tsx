import type React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DashboardPage from "./dashboard/page";
import LoginPage from "./login/page";
import RegisterPage from "./register/page";
import VerifyMagicLinkPage from "./auth/verify/page";
import Home from "./page";
import RootLayout, { metadata } from "./layout";

const mockReplace = vi.fn();
const mockRedirect = vi.fn();
const authFormMock = vi.fn();
const dashboardClientMock = vi.fn();
const verifyClientMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  redirect: (...args: unknown[]) => mockRedirect(...args),
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

describe("app pages", () => {
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

    const call = authFormMock.mock.calls[1]?.[0] as { mode: string; onSuccess: () => void };
    expect(call.mode).toBe("register");
    call.onSuccess();
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("renders dashboard wrapper", () => {
    render(<DashboardPage />);
    expect(screen.getByTestId("dashboard-client-mock")).toBeInTheDocument();
    expect(dashboardClientMock).toHaveBeenCalled();
  });

  it("resolves verify token from searchParams", async () => {
    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({ token: "abc-token" }) }));
    expect(screen.getByTestId("verify-client-mock")).toHaveTextContent("abc-token");

    render(await VerifyMagicLinkPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getAllByTestId("verify-client-mock")[1]).toHaveTextContent("null-token");
    expect(verifyClientMock).toHaveBeenCalledWith(null);
  });

  it("redirects home to login", () => {
    Home();
    expect(mockRedirect).toHaveBeenCalledWith("/login");
  });
});

describe("layout", () => {
  it("exports metadata and renders html/body structure", () => {
    expect(metadata.title).toBe("WaiComputer Web");
    expect(metadata.description).toBe("WaiComputer browser client");

    const element = RootLayout({ children: <div data-testid="layout-child">Child</div> });
    expect(element.type).toBe("html");
    expect((element.props as { lang: string }).lang).toBe("en");

    const body = (element.props as { children: React.ReactElement }).children;
    expect(body.type).toBe("body");
    expect((body.props as { className: string }).className).toContain("font-space-grotesk");
  });
});
