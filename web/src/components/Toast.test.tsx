import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast, type ToastTone } from "./Toast";

/**
 * Drives the toast API imperatively from a child rendered inside the provider.
 * Buttons let tests trigger show/error/success/clear without re-rendering.
 */
function Harness() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.show({ message: "info msg" })}>show-info</button>
      <button onClick={() => toast.show({ message: "succ msg", tone: "success" })}>
        show-success
      </button>
      <button
        onClick={() => toast.show({ message: "custom msg", durationMs: 1000 })}
      >
        show-custom
      </button>
      <button onClick={() => toast.error("boom")}>show-error</button>
      <button onClick={() => toast.success("yay")}>show-success-helper</button>
      <button onClick={() => toast.clear()}>clear</button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

describe("ToastProvider + useToast", () => {
  it("renders the notifications region wrapper without a nested live region", () => {
    renderWithProvider();
    const region = screen.getByRole("region", { name: "Notifications" });
    expect(region).toHaveClass("toast-stack");
    // The live-region level lives on each toast (role=status/alert); a redundant
    // aria-live on the wrapper would nest live regions and double-announce.
    expect(region).not.toHaveAttribute("aria-live");
  });

  it("shows an info toast with status role and info testid/class", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-info"));

    const toast = screen.getByTestId("toast-info");
    expect(toast).toHaveTextContent("info msg");
    expect(toast).toHaveClass("toast", "toast--info");
    // info/success use role=status, not alert.
    expect(toast).toHaveAttribute("role", "status");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error toast with alert role via the error() helper", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-error"));

    const toast = screen.getByTestId("toast-error");
    expect(toast).toHaveTextContent("boom");
    expect(toast).toHaveClass("toast--error");
    expect(toast).toHaveAttribute("role", "alert");
    expect(screen.getByRole("alert")).toBe(toast);
  });

  it("shows a success toast via the success() helper", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-success-helper"));

    const toast = screen.getByTestId("toast-success");
    expect(toast).toHaveTextContent("yay");
    expect(toast).toHaveClass("toast--success");
    expect(toast).toHaveAttribute("role", "status");
  });

  it("stacks multiple toasts and assigns unique keys/ids", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-info"));
    await user.click(screen.getByText("show-error"));

    expect(screen.getByText("info msg")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Dismiss" })).toHaveLength(2);
  });

  it("dismisses a single toast when its close button is clicked", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-info"));
    expect(screen.getByText("info msg")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("info msg")).not.toBeInTheDocument();
  });

  it("clear() removes every visible toast at once", async () => {
    const user = userEvent.setup();
    renderWithProvider();

    await user.click(screen.getByText("show-info"));
    await user.click(screen.getByText("show-error"));
    expect(screen.getAllByRole("button", { name: "Dismiss" })).toHaveLength(2);

    await user.click(screen.getByText("clear"));
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  describe("auto-dismiss timing", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    function fireClick(label: string) {
      // Fake timers break userEvent's internal delays, so dispatch directly.
      act(() => {
        screen.getByText(label).click();
      });
    }

    it("auto-dismisses an info toast after the default 3.2s lifetime", () => {
      renderWithProvider();
      fireClick("show-info");
      expect(screen.getByText("info msg")).toBeInTheDocument();

      // Still present just before the deadline.
      act(() => {
        vi.advanceTimersByTime(3199);
      });
      expect(screen.getByText("info msg")).toBeInTheDocument();

      // Gone once the default duration elapses.
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByText("info msg")).not.toBeInTheDocument();
    });

    it("keeps an error toast sticky (no auto-dismiss) past the default lifetime", () => {
      renderWithProvider();
      fireClick("show-error");
      expect(screen.getByText("boom")).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      // Error stays until manually closed.
      expect(screen.getByText("boom")).toBeInTheDocument();
    });

    it("honours an explicit durationMs override instead of the default", () => {
      renderWithProvider();
      fireClick("show-custom");
      expect(screen.getByText("custom msg")).toBeInTheDocument();

      // Not yet at the 1000ms custom deadline (and well under the 3.2s default).
      act(() => {
        vi.advanceTimersByTime(999);
      });
      expect(screen.getByText("custom msg")).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByText("custom msg")).not.toBeInTheDocument();
    });

    it("pauses the auto-dismiss timer while the toast is hovered (WCAG 2.2.1)", () => {
      renderWithProvider();
      fireClick("show-info");
      const toast = screen.getByTestId("toast-info");

      // Part-way through the 3.2s lifetime the pointer enters the toast.
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      act(() => {
        fireEvent.mouseEnter(toast);
      });

      // While hovered, time well past the original deadline must NOT dismiss it.
      act(() => {
        vi.advanceTimersByTime(10_000);
      });
      expect(screen.getByText("info msg")).toBeInTheDocument();

      // On leave the timer resumes and the toast dismisses after its lifetime.
      act(() => {
        fireEvent.mouseLeave(toast);
      });
      act(() => {
        vi.advanceTimersByTime(3200);
      });
      expect(screen.queryByText("info msg")).not.toBeInTheDocument();
    });

    it("pauses the auto-dismiss timer while focus is within the toast", () => {
      renderWithProvider();
      fireClick("show-info");
      const closeButton = screen.getByRole("button", { name: "Dismiss" });

      act(() => {
        vi.advanceTimersByTime(2000);
      });
      act(() => {
        fireEvent.focusIn(closeButton);
      });

      act(() => {
        vi.advanceTimersByTime(10_000);
      });
      expect(screen.getByText("info msg")).toBeInTheDocument();

      act(() => {
        fireEvent.focusOut(closeButton);
      });
      act(() => {
        vi.advanceTimersByTime(3200);
      });
      expect(screen.queryByText("info msg")).not.toBeInTheDocument();
    });
  });
});

describe("useToast fallback (no provider)", () => {
  const tones: ToastTone[] = ["info", "success", "error"];

  function FallbackHarness() {
    const toast = useToast();
    return (
      <div>
        <button onClick={() => toast.show({ message: "orphan", tone: tones[0] })}>
          show
        </button>
        <button onClick={() => toast.error("orphan-error")}>error</button>
        <button onClick={() => toast.success("orphan-success")}>success</button>
        <button onClick={() => toast.clear()}>clear</button>
      </div>
    );
  }

  let warn: ReturnType<typeof vi.spyOn>;
  let info: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    info = vi.spyOn(console, "info").mockImplementation(() => {});
  });
  afterEach(() => {
    warn.mockRestore();
    info.mockRestore();
  });

  it("does not throw and renders nothing into a toast stack", () => {
    render(<FallbackHarness />);
    expect(screen.queryByRole("region", { name: "Notifications" })).not.toBeInTheDocument();
  });

  it("show() warns instead of rendering a toast", async () => {
    const user = userEvent.setup();
    render(<FallbackHarness />);

    await user.click(screen.getByText("show"));

    expect(warn).toHaveBeenCalledWith("Toast:", "orphan");
    expect(screen.queryByTestId("toast-info")).not.toBeInTheDocument();
  });

  it("error() warns with the error label", async () => {
    const user = userEvent.setup();
    render(<FallbackHarness />);

    await user.click(screen.getByText("error"));

    expect(warn).toHaveBeenCalledWith("Toast (error):", "orphan-error");
  });

  it("success() logs via console.info", async () => {
    const user = userEvent.setup();
    render(<FallbackHarness />);

    await user.click(screen.getByText("success"));

    expect(info).toHaveBeenCalledWith("Toast (success):", "orphan-success");
    expect(warn).not.toHaveBeenCalled();
  });

  it("clear() is a safe no-op outside the provider", async () => {
    const user = userEvent.setup();
    render(<FallbackHarness />);

    await user.click(screen.getByText("clear"));

    expect(warn).not.toHaveBeenCalled();
    expect(info).not.toHaveBeenCalled();
  });
});
