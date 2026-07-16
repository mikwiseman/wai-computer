/**
 * Theme helpers — the single source of truth for the light/dark/system choice.
 *
 * Both the settings-only `ThemeAccentPicker` and the compact public `ThemeToggle`
 * import these so the storage key, the `data-theme` attribute, and the browser
 * chrome color (`<meta name="theme-color">`) can never drift apart. The accent
 * half of the picker stays in `ThemeAccentPicker.tsx`.
 *
 * The resolved-theme colors mirror the `viewport.themeColor` pair in
 * `app/layout.tsx` (Pearl `#f5f4f0`, Midnight `#111311`) and the `--bg` tokens.
 */

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "wai_theme";
export const DEFAULT_THEME: ThemeChoice = "system";

// `useSyncExternalStore` must return the value just written when it notifies
// same-tab subscribers. Keep an in-memory snapshot only when browser storage
// rejects a write (private browsing, quota, or policy restrictions); the next
// successful write or cross-tab storage event makes localStorage authoritative
// again.
let themeSnapshot: ThemeChoice = DEFAULT_THEME;
let themeSnapshotIsAuthoritative = false;

/** Browser chrome color for each resolved theme — kept in step with `--bg`. */
const META_THEME_COLOR: Record<"light" | "dark", string> = {
  light: "#f5f4f0",
  dark: "#111311",
};

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

/** Collapse "system" to the concrete light/dark the OS is currently asking for. */
function resolveTheme(theme: ThemeChoice): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

/**
 * Keep `<meta name="theme-color">` matching the resolved theme.
 *
 * The SSR layout ships two OS-`media`-scoped tags so the chrome is right before
 * hydration. Once JS owns the choice we drop that `media` scoping and pin the
 * content, so an explicit light/dark override wins over the OS preference (the
 * media tags would otherwise keep following the OS and ignore the override).
 */
function applyMetaThemeColor(resolved: "light" | "dark"): void {
  if (typeof document === "undefined") return;
  const color = META_THEME_COLOR[resolved];
  const metas = document.querySelectorAll('meta[name="theme-color"]');
  if (metas.length === 0) {
    const meta = document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    meta.setAttribute("content", color);
    document.head.appendChild(meta);
    return;
  }
  metas.forEach((meta) => {
    meta.removeAttribute("media");
    meta.setAttribute("content", color);
  });
}

/** Apply a theme choice to the document: `data-theme` + browser chrome color. */
export function applyTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  applyMetaThemeColor(resolveTheme(theme));
}

/** getSnapshot for `useSyncExternalStore` — the current stored choice. */
export function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return DEFAULT_THEME;
  if (themeSnapshotIsAuthoritative) return themeSnapshot;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    themeSnapshot = isThemeChoice(raw) ? raw : DEFAULT_THEME;
    return themeSnapshot;
  } catch {
    return themeSnapshot;
  }
}

// Same-tab subscribers to the stored theme. Cross-tab changes arrive via the
// `storage` event; same-tab writes are broadcast explicitly (that event never
// fires in the tab that made the change).
const themeListeners = new Set<() => void>();

/**
 * subscribe for `useSyncExternalStore`: fire `callback` whenever the stored
 * theme changes, from this tab (a `writeStoredTheme` call, including the
 * settings picker's) or another tab (the `storage` event).
 */
export function subscribeStoredTheme(callback: () => void): () => void {
  themeListeners.add(callback);
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) {
      themeSnapshot = isThemeChoice(event.newValue) ? event.newValue : DEFAULT_THEME;
      themeSnapshotIsAuthoritative = false;
      callback();
    }
  };
  if (typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
  }
  return () => {
    themeListeners.delete(callback);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function writeStoredTheme(theme: ThemeChoice): void {
  if (typeof window === "undefined") return;
  themeSnapshot = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    themeSnapshotIsAuthoritative = false;
  } catch {
    themeSnapshotIsAuthoritative = true;
  }
  for (const listener of themeListeners) listener();
}
