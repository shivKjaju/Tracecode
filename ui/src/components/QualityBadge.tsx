"use client";

/**
 * QualityBadge — shows auto_outcome or manual_outcome as a colored pill.
 */

interface Props {
  outcome: string | null | undefined;
  /** If true, renders as a smaller inline pill */
  small?: boolean;
}

const STYLES: Record<string, string> = {
  success:   "bg-[#1c3a28] text-[var(--success)] border border-[var(--success)]/30",
  partial:   "bg-[#2e2006] text-[var(--partial)] border border-[var(--partial)]/30",
  incomplete:"bg-[#3a1a1a] text-[var(--fail)] border border-[var(--fail)]/30",
  abandoned: "bg-[#3a1a1a] text-[var(--fail)] border border-[var(--fail)]/30",
};

export function QualityBadge({ outcome, small }: Props) {
  if (!outcome) {
    return (
      <span className={`${small ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1"} rounded-full bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)]`}>
        pending
      </span>
    );
  }
  const cls = STYLES[outcome] ?? "bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)]";
  return (
    <span className={`${small ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1"} rounded-full font-medium ${cls}`}>
      {outcome}
    </span>
  );
}
