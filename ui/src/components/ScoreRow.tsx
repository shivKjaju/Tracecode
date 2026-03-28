"use client";

import { useState } from "react";

interface Props {
  label: string;
  value: string | number | null | undefined;
  tooltip?: string;
  subtext?: string;
  /** 0-1 fill ratio for the progress bar. Omit to hide bar. */
  fill?: number | null;
  fillColor?: string;
}

export function ScoreRow({ label, value, tooltip, subtext, fill, fillColor = "var(--accent)" }: Props) {
  const display = value == null ? "—" : String(value);
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="flex flex-col gap-1 py-2 border-b border-[var(--border)] last:border-0">
      <div className="flex justify-between items-baseline">
        <div className="flex items-center gap-1.5">
          <span className="text-sm text-[var(--muted)]">{label}</span>
          {tooltip && (
            <div className="relative">
              <button
                onMouseEnter={() => setShowTip(true)}
                onMouseLeave={() => setShowTip(false)}
                className="text-[var(--muted)] opacity-40 hover:opacity-80 transition-opacity text-xs leading-none"
                tabIndex={-1}
              >
                ?
              </button>
              {showTip && (
                <div className="absolute left-0 top-5 z-10 w-56 rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs text-[var(--muted)] shadow-lg leading-relaxed">
                  {tooltip}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="text-right">
          <span className="text-sm font-mono font-medium text-[var(--text)]">{display}</span>
          {subtext && (
            <span className="ml-1 text-xs text-[var(--muted)]">{subtext}</span>
          )}
        </div>
      </div>
      {fill != null && (
        <div className="h-1 rounded-full bg-[var(--border)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${Math.min(100, Math.round(fill * 100))}%`, backgroundColor: fillColor }}
          />
        </div>
      )}
    </div>
  );
}
