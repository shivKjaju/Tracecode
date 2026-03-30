"use client";

/**
 * VerdictBadge — trust verdict pill with five states.
 */

interface Props {
  verdict: string | null | undefined;
  small?: boolean;
}

const VERDICT_CONFIG: Record<
  string,
  { label: string; cls: string }
> = {
  trusted: {
    label: "Trusted",
    cls: "bg-[#1c3a28] text-[var(--success)] border border-[var(--success)]/40",
  },
  trusted_with_caveats: {
    label: "Trusted with Caveats",
    cls: "bg-[#2e2c06] text-[#d4b84a] border border-[#d4b84a]/40",
  },
  review_required: {
    label: "Review Required",
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

export function VerdictBadge({ verdict, small }: Props) {
  const size = small ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1";

  if (!verdict) {
    return (
      <span
        className={`${size} rounded-full bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)] font-medium`}
      >
        pending
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
