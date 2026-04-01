"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type SessionSummary } from "@/lib/api";
import { fmtTime, fmtDuration } from "@/lib/format";
import { VerdictBadge } from "@/components/VerdictBadge";

/** Top anomaly tags shown on the feed row (major only, max 2). */
function AnomalyTags({ session }: { session: SessionSummary }) {
  const tags: string[] = [];

  if (session.catastrophic_count > 0)
    tags.push(`${session.catastrophic_count} command${session.catastrophic_count > 1 ? "s" : ""} blocked`);
  else if (session.risky_count > 0)
    tags.push(`${session.risky_count} risky command${session.risky_count > 1 ? "s" : ""}`);

  if (session.sensitive_files_touched) tags.push("config/env files modified");

  // Derive cheap major signals from summary fields
  if (session.tree_dirty) tags.push("uncommitted changes");
  if (
    session.persistence_reliable &&
    session.persistence_rate != null &&
    session.persistence_rate < 0.5
  )
    tags.push("most edits reverted");

  const shown = tags.slice(0, 2);
  if (shown.length === 0) return null;

  return (
    <div className="flex items-center gap-2 flex-wrap mt-0.5">
      {shown.map((t) => (
        <span
          key={t}
          className="text-xs text-[var(--muted)] opacity-70"
        >
          {t}
        </span>
      ))}
    </div>
  );
}

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
        <div className="py-16 text-center space-y-4">
          <p className="text-sm font-medium text-[var(--text)]">No sessions yet</p>
          <p className="text-sm text-[var(--muted)]">
            Tracecode records Claude sessions automatically.
            <br />
            Run Claude in any project, then come back here.
          </p>
          <div className="inline-block text-left mt-2 px-4 py-3 rounded border border-[var(--border)] bg-[var(--surface)]">
            <code className="block text-xs font-mono text-[var(--muted)]">$ cd your-project</code>
            <code className="block text-xs font-mono text-[var(--text)]">$ claude</code>
          </div>
          <p className="text-xs text-[var(--muted)] opacity-60 mt-2">
            Want to verify setup?{" "}
            <code className="font-mono">tracecode doctor</code>
          </p>
        </div>
      ) : (
        <>
          {total === 1 && (
            <div className="mb-4 px-4 py-3 rounded border border-[var(--border)] bg-[var(--surface)] text-sm text-[var(--muted)]">
              Your first session was recorded. Click the row to see the trust verdict and what to inspect first.
            </div>
          )}

          <div className="rounded border border-[var(--border)] overflow-hidden">
            {sessions.map((s, i) => (
              <Link
                key={s.id}
                href={`/sessions?id=${s.id}`}
                className={`flex items-center gap-4 px-4 py-3 hover:bg-[var(--surface)] transition-colors border-b border-[var(--border)] last:border-0 ${
                  i % 2 === 0 ? "" : "bg-[var(--surface)]/40"
                }`}
              >
                {/* Verdict pill — primary signal */}
                <div className="shrink-0">
                  <VerdictBadge
                    verdict={s.verdict}
                    small
                    endedAt={s.ended_at}
                    hasData={s.files_touched !== null}
                  />
                </div>

                {/* Project / anomaly tags */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[var(--text)] truncate">
                      {s.project_name}
                    </span>
                    {s.git_branch && (
                      <span className="text-xs text-[var(--muted)] font-mono shrink-0">
                        {s.git_branch}
                      </span>
                    )}
                  </div>
                  <AnomalyTags session={s} />
                </div>

                {/* Duration + time */}
                <div className="shrink-0 text-right text-xs text-[var(--muted)]">
                  {s.duration_seconds != null && (
                    <div>{fmtDuration(s.duration_seconds)}</div>
                  )}
                  <div className="opacity-60">{fmtTime(s.started_at)}</div>
                </div>
              </Link>
            ))}
          </div>

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
