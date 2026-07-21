"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/// Top-nav RU/EN switcher.
///
/// Maps the current pathname to its parallel-route sibling: `/` ↔ `/ru`,
/// `/pricing` ↔ `/ru/pricing`, `/billing` ↔ `/ru/billing`. Anything else
/// (auth pages, share links, etc.) falls back to the locale root.
export function LocaleSwitcher({
  current,
}: {
  current: "en" | "ru";
}) {
  const pathname = usePathname() || "/";

  const toEn = stripRuPrefix(pathname);
  const toRu = addRuPrefix(pathname);

  return (
    <div
      className="locale-switcher"
      role="group"
      aria-label={current === "ru" ? "Язык" : "Language"}
    >
      <Link
        href={toEn}
        className={`locale-switcher__item${current === "en" ? " is-active" : ""}`}
        aria-current={current === "en" ? "true" : undefined}
        prefetch={false}
      >
        EN
      </Link>
      <span className="locale-switcher__sep" aria-hidden="true">
        ·
      </span>
      <Link
        href={toRu}
        className={`locale-switcher__item${current === "ru" ? " is-active" : ""}`}
        aria-current={current === "ru" ? "true" : undefined}
        prefetch={false}
      >
        RU
      </Link>
    </div>
  );
}

function stripRuPrefix(pathname: string): string {
  if (pathname === "/ru") return "/";
  if (pathname.startsWith("/ru/")) return pathname.slice(3) || "/";
  return pathname;
}

function addRuPrefix(pathname: string): string {
  if (pathname === "/ru" || pathname.startsWith("/ru/")) return pathname;
  if (pathname === "/") return "/ru";
  return `/ru${pathname}`;
}
