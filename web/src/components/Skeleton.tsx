"use client";

import type { CSSProperties } from "react";

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  radius?: string | number;
  /** Reserves block-level vertical space; use false for inline tokens. */
  block?: boolean;
  /** Show multiple stacked lines. */
  lines?: number;
  className?: string;
  label?: string;
}

/**
 * Skeleton loading shimmer. Honours `prefers-reduced-motion` via the global
 * rule in globals.css. Default to a single 1-line block.
 */
export function Skeleton({
  width,
  height = "1em",
  radius = "6px",
  block = true,
  lines = 1,
  className,
  label = "Loading",
}: SkeletonProps) {
  const style: CSSProperties = {
    width: width ?? "100%",
    height,
    borderRadius: typeof radius === "number" ? `${radius}px` : radius,
  };
  if (lines > 1) {
    return (
      <div
        className={["skeleton-stack", className].filter(Boolean).join(" ")}
        role="status"
        aria-label={label}
      >
        {Array.from({ length: lines }).map((_, i) => (
          <span
            key={i}
            className="skeleton skeleton--line"
            style={{
              ...style,
              // Last line is shorter so the block reads as text-shaped.
              width: i === lines - 1 ? "62%" : style.width,
            }}
          />
        ))}
      </div>
    );
  }
  return (
    <span
      className={[
        "skeleton",
        block ? "skeleton--block" : "skeleton--inline",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
      role="status"
      aria-label={label}
    />
  );
}
