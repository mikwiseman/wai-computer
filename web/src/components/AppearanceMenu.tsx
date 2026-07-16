"use client";

import { useEffect, useRef, useState } from "react";
import { Palette, X } from "lucide-react";
import { ThemeAccentPicker } from "@/components/ThemeAccentPicker";
import styles from "./AppearanceMenu.module.css";

type Locale = "en" | "ru";

const COPY = {
  en: {
    open: "Appearance",
    title: "Appearance",
    close: "Close appearance",
  },
  ru: {
    open: "Оформление",
    title: "Оформление",
    close: "Закрыть оформление",
  },
} satisfies Record<Locale, Record<string, string>>;

export function AppearanceMenu({ locale }: { locale: Locale }) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const copy = COPY[locale];

  useEffect(() => {
    if (!isOpen) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setIsOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls="appearance-menu-popover"
        onClick={() => setIsOpen((value) => !value)}
      >
        <Palette size={16} strokeWidth={1.8} aria-hidden="true" />
        <span>{copy.open}</span>
      </button>

      {isOpen ? (
        <div
          id="appearance-menu-popover"
          className={styles.popover}
          role="dialog"
          aria-modal="false"
          aria-label={copy.title}
        >
          <header className={styles.header}>
            <strong>{copy.title}</strong>
            <button
              type="button"
              className={styles.close}
              aria-label={copy.close}
              onClick={() => {
                setIsOpen(false);
                triggerRef.current?.focus();
              }}
            >
              <X size={16} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </header>
          <ThemeAccentPicker locale={locale} />
        </div>
      ) : null}
    </div>
  );
}
