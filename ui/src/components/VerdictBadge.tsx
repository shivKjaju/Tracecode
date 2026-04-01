"use client";

/**
 * VerdictBadge — trust verdict pill.
 *
 * Real verdict states (trusted → blocked) use color-coded pills.
 * System states (in-progress, no-data) are intentionally muted and
 * non-competitive — they must not read as trust judgments.
 */

interface Props {
  verdict: string | null | undefined;
  small?: boolean;
  endedAt?: number | null;
  hasData?: boolean;
}

const VERDICT_CONFIG: Record<string, { label: string; cls: string }> = {
  trusted: {
    label: "Trusted",
    cls: "bg-[#1c3a28] text-[var(--success)] border border-[var(--success)]/40",
  },
  trusted_with_caveats: {
    label: "Trusted with Caveats",
    cls: "bg-[#2e2c06] text-[#d4b84a] border border-[#d4b84a]/40",
  },
  review_required: {
    label: "Needs Review",
    cls: "bg-[#2e1a06] text-[#e08030] border border-[#e08030]/40",
  },
  high_risk: {
    label: "High Risk",
    cls: "bg-[#3a1a1a] text-[var(--fail)] border border-[var(--fail)]/40",
  },
  blocked: {
    label: "Blocked",
    cls: "bg-[var(--fail)] text-[var(--bg)] border border-[var(--fail)]",
  },
};

export function VerdictBadge({ verdict, small, endedAt, hasData }: Props) {
  const size = small ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1";

  if (!verdict) {
    if (!endedAt) {
      // Session still running — label as a live system state, not a verdict
      return (
        <span
          className={`${size} rounded-full text-[var(--muted)] opacity-50 italic tracking-normal`}
        >
          In progress
        </span>
      );
    }
    if (!hasData) {
      // Ended with no scorable data
      return (
        <span
          className={`${size} rounded-full text-[var(--muted)] opacity-35`}
        >
          No data
        </span>
      );
    }
    // Ended with data but verdict not yet computed (will resolve on detail view)
    return (
      <span className={`${size} text-[var(--muted)] opacity-25 font-mono`}>
        —
      </span>
    );
  }

  const cfg = VERDICT_CONFIG[verdict] ?? {
    label: verdict,
    cls: "bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)]",
  };

  return (
    <span className={`${size} rounded-full font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}
