"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type SessionSummary } from "@/lib/api";
import { fmtTime, fmtDuration, pct } from "@/lib/format";
import { QualityBadge } from "@/components/QualityBadge";

export default function FeedPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 25;

  useEffect(() => {
    setLoading(true);
    api
      .listSessions(limit, offset)
      .then((r) => {
        setSessions(r.sessions);
        setTotal(r.total);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [offset]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">Sessions</h1>
          {!loading && (
            <p className="text-sm text-[var(--muted)] mt-0.5">{total} total</p>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded border border-[var(--fail)]/40 bg-[#3a1a1a]/40 px-4 py-3 text-sm text-[var(--fail)] mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-[var(--muted)] py-12 text-center">Loading…</div>
      ) : sessions.length === 0 ? (
        <div className="text-sm text-[var(--muted)] py-12 text-center">
          No sessions recorded yet. Run <code className="font-mono text-[var(--accent)]">claude</code> in any project to get started.
        </div>
      ) : (
        <>
          <div className="rounded border border-[var(--border)] overflow-hidden">
            {/* Header */}
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-4 py-2 bg-[var(--surface)] border-b border-[var(--border)] text-xs text-[var(--muted)]">
              <span>project / branch</span>
              <span className="w-20 text-right">duration</span>
              <span className="w-20 text-right">quality</span>
              <span className="w-24 text-center">outcome</span>
              <span className="w-28 text-right">started</span>
            </div>

            {sessions.map((s, i) => (
              <Link
                key={s.id}
                href={`/sessions?id=${s.id}`}
                className={`grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-4 py-3 hover:bg-[var(--surface)] transition-colors border-b border-[var(--border)] last:border-0 ${i % 2 === 0 ? "" : "bg-[var(--surface)]/40"}`}
              >
                {/* Project / branch */}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[var(--text)] truncate">
                      {s.project_name}
                    </span>
                    {s.catastrophic_count > 0 && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[#3a1a1a] text-[var(--fail)] border border-[var(--fail)]/30 shrink-0">
                        ⛔ {s.catastrophic_count} blocked
                      </span>
                    )}
                    {s.risky_count > 0 && s.catastrophic_count === 0 && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[#2e2006] text-[var(--partial)] border border-[var(--partial)]/30 shrink-0">
                        ⚠ {s.risky_count} risky
                      </span>
                    )}
                    {s.risky_count > 0 && s.catastrophic_count > 0 && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[#2e2006] text-[var(--partial)] border border-[var(--partial)]/30 shrink-0">
                        ⚠ {s.risky_count}
                      </span>
                    )}
                  </div>
                  {s.git_branch && (
                    <span className="text-xs text-[var(--muted)] font-mono truncate block">
                      {s.git_branch}
                    </span>
                  )}
                </div>

                {/* Duration */}
                <div className="w-20 text-right text-sm text-[var(--muted)] self-center">
                  {fmtDuration(s.duration_seconds)}
                </div>

                {/* Quality score */}
                <div className="w-20 text-right text-sm font-mono self-center">
                  {s.quality_score != null ? (
                    <span
                      style={{
                        color:
                          s.quality_score >= 0.7
                            ? "var(--success)"
                            : s.quality_score >= 0.4
                            ? "var(--partial)"
                            : "var(--fail)",
                      }}
                    >
                      {pct(s.quality_score)}
                    </span>
                  ) : (
                    <span className="text-[var(--muted)]">—</span>
                  )}
                </div>

                {/* Outcome badge */}
                <div className="w-24 flex items-center justify-center">
                  <QualityBadge
                    outcome={s.manual_outcome ?? s.auto_outcome}
                    small
                  />
                </div>

                {/* Timestamp */}
                <div className="w-28 text-right text-xs text-[var(--muted)] self-center">
                  {fmtTime(s.started_at)}
                </div>
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {total > limit && (
            <div className="flex justify-center gap-3 mt-6">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className="px-4 py-1.5 rounded border border-[var(--border)] text-sm text-[var(--text)] disabled:opacity-30 hover:border-[var(--accent)] transition-colors"
              >
                ← Newer
              </button>
              <span className="text-sm text-[var(--muted)] self-center">
                {offset + 1}–{Math.min(offset + limit, total)} of {total}
              </span>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
                className="px-4 py-1.5 rounded border border-[var(--border)] text-sm text-[var(--text)] disabled:opacity-30 hover:border-[var(--accent)] transition-colors"
              >
                Older →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
