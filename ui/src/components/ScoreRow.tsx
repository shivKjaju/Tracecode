"use client";

/**
 * ScoreRow — a single labeled metric in the scores panel.
 */

interface Props {
  label: string;
  value: string | number | null | undefined;
  subtext?: string;
  /** 0-1 fill ratio for the progress bar. Omit to hide bar. */
  fill?: number | null;
  fillColor?: string;
}

export function ScoreRow({ label, value, subtext, fill, fillColor = "var(--accent)" }: Props) {
  const display = value == null ? "—" : String(value);
  return (
    <div className="flex flex-col gap-1 py-2 border-b border-[var(--border)] last:border-0">
      <div className="flex justify-between items-baseline">
        <span className="text-sm text-[var(--muted)]">{label}</span>
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
