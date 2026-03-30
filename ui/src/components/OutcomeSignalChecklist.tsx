"use client";

import type { OutcomeSignal } from "@/lib/api";

interface Props {
  signals: OutcomeSignal[];
}

export function OutcomeSignalChecklist({ signals }: Props) {
  return (
    <div className="space-y-1.5">
      {signals.map((s) => {
        const icon = !s.reliable ? "·" : s.passed ? "✓" : "✗";
        const color = !s.reliable
          ? "text-[var(--muted)]"
          : s.passed
          ? "text-[var(--success)]"
          : "text-[var(--fail)]";
        return (
          <div key={s.label} className="flex items-center gap-2.5">
            <span className={`font-mono text-sm w-3 shrink-0 ${color}`}>{icon}</span>
            <span className={`text-sm ${s.reliable ? "text-[var(--text)]" : "text-[var(--muted)]"}`}>
              {s.label}
            </span>
            {!s.reliable && (
              <span className="text-xs text-[var(--muted)] opacity-60">no data</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
