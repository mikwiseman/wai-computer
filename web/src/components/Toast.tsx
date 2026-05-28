"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "info" | "success" | "error";

interface ToastInput {
  message: string;
  tone?: ToastTone;
  /** Override the default lifetime (ms). Errors default to sticky. */
  durationMs?: number;
}

interface ToastEntry extends ToastInput {
  id: number;
}

interface ToastApi {
  show: (input: ToastInput) => void;
  /** Convenience: show error tone, sticky by default. */
  error: (message: string) => void;
  /** Convenience: show success tone, auto-dismiss. */
  success: (message: string) => void;
  /** Clear every visible toast. */
  clear: () => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATION = 3200;

/**
 * Single toast stack. Auto-dismisses success/info after 3.2s; errors stick
 * until manually closed (matches Mac alert behavior). Honours
 * `prefers-reduced-motion` via the global rule in globals.css.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    ({ message, tone = "info", durationMs }: ToastInput) => {
      const id = ++idRef.current;
      const entry: ToastEntry = { id, message, tone, durationMs };
      setToasts((current) => [...current, entry]);
      const lifetime =
        durationMs ?? (tone === "error" ? Infinity : DEFAULT_DURATION);
      if (Number.isFinite(lifetime)) {
        window.setTimeout(() => dismiss(id), lifetime);
      }
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      error: (message) => show({ message, tone: "error" }),
      success: (message) => show({ message, tone: "success" }),
      clear: () => setToasts([]),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="toast-stack"
        role="region"
        aria-label="Notifications"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: ToastEntry;
  onDismiss: () => void;
}) {
  useEffect(() => {
    // Re-trigger entrance animation on mount.
  }, []);

  return (
    <div
      className={`toast toast--${toast.tone ?? "info"}`}
      role={toast.tone === "error" ? "alert" : "status"}
      data-testid={`toast-${toast.tone ?? "info"}`}
    >
      <p>{toast.message}</p>
      <button
        type="button"
        className="toast__close"
        aria-label="Dismiss"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Graceful fallback so a stray useToast outside the provider doesn't
    // crash the app — it just no-ops with console warnings.
    return {
      show: ({ message }) => {
        if (typeof console !== "undefined") console.warn("Toast:", message);
      },
      error: (message) => {
        if (typeof console !== "undefined") console.warn("Toast (error):", message);
      },
      success: (message) => {
        if (typeof console !== "undefined") console.info("Toast (success):", message);
      },
      clear: () => {},
    };
  }
  return ctx;
}
