"use client";

/**
 * Session detail page — accessed via /sessions?id=<uuid>
 *
 * Uses query params instead of a dynamic route so the app can be
 * exported as a static site (Next.js output: "export").
 */

import { Suspense, useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, type SessionDetail, type DiffResponse, type RiskyCommand } from "@/lib/api";
import { fmtTime, fmtDuration, shortSha, pct, diffStats } from "@/lib/format";
import { QualityBadge } from "@/components/QualityBadge";
import { ScoreRow } from "@/components/ScoreRow";
import { FileTouchTable } from "@/components/FileTouchTable";
import { DiffViewer } from "@/components/DiffViewer";

function SessionDetailInner() {
  const params = useSearchParams();
  const id = params.get("id");

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [diff, setDiff] = useState<DiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [diffLoading, setDiffLoading] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Manual enrichment state
  const [manualOutcome, setManualOutcome] = useState<string>("");
  const [note, setNote] = useState("");
  const [perceivedQuality, setPerceivedQuality] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api
      .getSession(id)
      .then((s) => {
        setSession(s);
        setManualOutcome(s.manual_outcome ?? "");
        setNote(s.note ?? "");
        setPerceivedQuality(s.perceived_quality ?? null);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const loadDiff = useCallback(() => {
    if (!id || diff) return;
    setDiffLoading(true);
    api
      .getDiff(id)
      .then(setDiff)
      .catch((e) => setError(String(e)))
      .finally(() => setDiffLoading(false));
  }, [id, diff]);

  const handleShowDiff = () => {
    setShowDiff(true);
    loadDiff();
  };

  const saveManual = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const updated = await api.patchSession(id, {
        manual_outcome: (manualOutcome || null) as
          | "success"
          | "partial"
          | "abandoned"
          | null,
        note: note || null,
        perceived_quality: perceivedQuality,
      });
      setSession(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!id) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No session ID provided.{" "}
        <Link href="/" className="text-[var(--accent)]">
          Back to sessions
        </Link>
      </p>
    );
  }

  if (loading) {
    return (
      <div className="text-sm text-[var(--muted)] py-12 text-center">
        Loading…
      </div>
    );
  }

  if (error && !session) {
    return (
      <div className="rounded border border-[var(--fail)]/40 bg-[#3a1a1a]/40 px-4 py-3 text-sm text-[var(--fail)]">
        {error}
      </div>
    );
  }

  if (!session) return null;

  const effectiveOutcome = session.manual_outcome ?? session.auto_outcome;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
        <Link href="/" className="hover:text-[var(--accent)] transition-colors">
          Sessions
        </Link>
        <span>/</span>
        <span className="font-mono text-xs">{id.slice(0, 8)}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">
            {session.project_name}
          </h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-[var(--muted)]">
            {session.git_branch && (
              <span className="font-mono">{session.git_branch}</span>
            )}
            <span>{fmtTime(session.started_at)}</span>
            {session.duration_seconds != null && (
              <span>{fmtDuration(session.duration_seconds)}</span>
            )}
          </div>
        </div>
        <QualityBadge outcome={effectiveOutcome} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Scores panel */}
        <div className="md:col-span-1 rounded border border-[var(--border)] bg-[var(--surface)] p-4">
          <p className="text-xs text-[var(--muted)] uppercase tracking-wider mb-3">
            Scores
          </p>
          <ScoreRow
            label="Quality"
            value={pct(session.quality_score)}
            tooltip="Overall session quality. Weighted mix of Outcome (60%) and focus (40%). Higher = Claude shipped something real and stayed on track."
            fill={session.quality_score}
            fillColor={
              (session.quality_score ?? 0) >= 0.7
                ? "var(--success)"
                : (session.quality_score ?? 0) >= 0.4
                ? "var(--partial)"
                : "var(--fail)"
            }
          />
          <ScoreRow
            label="Outcome"
            value={`${session.outcome_score ?? "—"} / 4`}
            tooltip="4 binary signals, 1 point each: committed code, clean git tree at end, tests passed, >70% of touched files survived to git."
            fill={
              session.outcome_score != null ? session.outcome_score / 4 : null
            }
          />
          <ScoreRow
            label="Wandering"
            value={pct(session.wandering_score)}
            tooltip="Ratio of 'hot files' (touched 3+ times) to total files touched. High = Claude kept revisiting the same files, suggesting it was stuck or going in circles."
            fill={session.wandering_score}
            fillColor="var(--partial)"
          />
          {session.persistence_rate != null && (
            <ScoreRow
              label={`Persistence${session.persistence_reliable ? "" : " ~"}`}
              tooltip="Fraction of files Claude touched that actually survived to git. Low = Claude made changes that were reverted or discarded."
              value={pct(session.persistence_rate)}
              fill={session.persistence_rate}
              fillColor="var(--success)"
            />
          )}
        </div>

        {/* Metadata + calibration */}
        <div className="md:col-span-2 space-y-4">
          {/* Session metadata */}
          <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
            <p className="text-xs text-[var(--muted)] uppercase tracking-wider mb-3">
              Session
            </p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div className="text-[var(--muted)]">Project path</div>
              <div className="font-mono text-xs text-[var(--text)] truncate">
                {session.project_path}
              </div>

              <div className="text-[var(--muted)]">SHA before → after</div>
              <div className="font-mono text-xs text-[var(--text)]">
                {shortSha(session.git_commit_before)} →{" "}
                {shortSha(session.git_commit_after)}
              </div>

              <div className="text-[var(--muted)]">Commits during</div>
              <div className="text-[var(--text)]">
                {session.commits_during ?? "—"}
              </div>

              <div className="text-[var(--muted)]">Tree dirty at end</div>
              <div
                className={
                  session.tree_dirty
                    ? "text-[var(--partial)]"
                    : "text-[var(--success)]"
                }
              >
                {session.tree_dirty == null
                  ? "—"
                  : session.tree_dirty
                  ? "yes"
                  : "no"}
              </div>

              <div className="text-[var(--muted)]">Files touched</div>
              <div className="text-[var(--text)]">
                {session.files_touched ?? "—"}
                {session.hot_files ? ` (${session.hot_files} hot)` : ""}
              </div>

              <div className="text-[var(--muted)]">Test outcome</div>
              <div
                className={
                  session.test_outcome === "pass"
                    ? "text-[var(--success)]"
                    : session.test_outcome === "fail"
                    ? "text-[var(--fail)]"
                    : "text-[var(--muted)]"
                }
              >
                {session.test_outcome ?? "—"}
                {session.test_source && (
                  <span className="ml-1 text-xs text-[var(--muted)]">
                    ({session.test_source})
                  </span>
                )}
              </div>

              <div className="text-[var(--muted)]">Exit code</div>
              <div
                className={
                  session.claude_exit_code === 0
                    ? "text-[var(--success)]"
                    : "text-[var(--fail)]"
                }
              >
                {session.claude_exit_code ?? "—"}
              </div>
            </div>
          </div>

          {/* Calibration */}
          <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
            <p className="text-xs text-[var(--muted)] uppercase tracking-wider mb-3">
              Calibration
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-[var(--muted)] block mb-1">
                  Override outcome
                </label>
                <select
                  value={manualOutcome}
                  onChange={(e) => setManualOutcome(e.target.value)}
                  className="w-full text-sm bg-[var(--bg)] border border-[var(--border)] rounded px-3 py-1.5 text-[var(--text)] focus:border-[var(--accent)] outline-none"
                >
                  <option value="">
                    — auto ({session.auto_outcome ?? "pending"})
                  </option>
                  <option value="success">success</option>
                  <option value="partial">partial</option>
                  <option value="abandoned">abandoned</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-[var(--muted)] block mb-1">
                  Perceived quality (1–5)
                </label>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      onClick={() =>
                        setPerceivedQuality(perceivedQuality === v ? null : v)
                      }
                      className={`w-8 h-8 rounded text-sm font-mono border transition-colors ${
                        perceivedQuality === v
                          ? "bg-[var(--accent)] border-[var(--accent)] text-[var(--bg)]"
                          : "border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]"
                      }`}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-[var(--muted)] block mb-1">
                  Note
                </label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="w-full text-sm bg-[var(--bg)] border border-[var(--border)] rounded px-3 py-1.5 text-[var(--text)] focus:border-[var(--accent)] outline-none resize-none"
                  placeholder="What happened in this session?"
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={saveManual}
                  disabled={saving}
                  className="px-4 py-1.5 rounded bg-[var(--accent)] text-[var(--bg)] text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                {saved && (
                  <span className="text-sm text-[var(--success)] transition-opacity">
                    ✓ Saved
                  </span>
                )}
              </div>
              {error && <p className="text-xs text-[var(--fail)]">{error}</p>}
            </div>
          </div>
        </div>
      </div>

      {/* Risky commands */}
      {session.risky_commands.length > 0 && (
        <div className="rounded border border-[var(--partial)]/40 bg-[#2e2006]/40 p-4">
          <p className="text-xs text-[var(--partial)] uppercase tracking-wider mb-3">
            Flagged Commands ({session.risky_commands.length})
          </p>
          <div className="space-y-2">
            {session.risky_commands.map((r) => (
              <div key={r.id} className="flex items-start gap-3">
                <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${
                  r.tier === "catastrophic"
                    ? "bg-[#3a1a1a] text-[var(--fail)] border border-[var(--fail)]/30"
                    : "bg-[#2e2006] text-[var(--partial)] border border-[var(--partial)]/30"
                }`}>
                  {r.tier === "catastrophic" ? "blocked" : "risky"}
                </span>
                <div className="min-w-0">
                  <p className="text-xs text-[var(--muted)]">{r.reason}</p>
                  <p className="font-mono text-xs text-[var(--text)] truncate mt-0.5">{r.command}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* File touches */}
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--muted)] uppercase tracking-wider mb-3">
          File Touches
          {session.file_touches.length > 0 && (
            <span className="ml-2 normal-case text-[var(--text)]">
              ({session.file_touches.length} files)
            </span>
          )}
        </p>
        <FileTouchTable touches={session.file_touches} />
      </div>

      {/* Git diff */}
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="flex items-start justify-between mb-1">
          <div>
            <p className="text-xs text-[var(--muted)] uppercase tracking-wider">
              Net Diff
            </p>
            <p className="text-xs text-[var(--muted)] mt-0.5 normal-case">
              All code changes from session start → end
              {session.git_commit_before && (
                <span className="font-mono ml-1 opacity-60">
                  ({shortSha(session.git_commit_before)} → {shortSha(session.git_commit_after) || "HEAD"})
                </span>
              )}
            </p>
          </div>
          {!showDiff && (
            <button
              onClick={handleShowDiff}
              className="text-xs text-[var(--accent)] hover:underline shrink-0 mt-0.5"
            >
              Show diff
            </button>
          )}
        </div>
        {showDiff && (
          <div className="mt-3">
            {diffLoading ? (
              <p className="text-sm text-[var(--muted)]">Loading…</p>
            ) : diff ? (
              diff.available && diff.diff.trim() ? (
                <>
                  {(() => {
                    const { added, removed, files } = diffStats(diff.diff);
                    return (
                      <div className="flex gap-4 mb-2 text-sm font-mono">
                        <span className="text-[var(--success)]">+{added} lines</span>
                        <span className="text-[var(--fail)]">−{removed} lines</span>
                        <span className="text-[var(--muted)]">{files} file{files !== 1 ? "s" : ""}</span>
                      </div>
                    );
                  })()}
                  <div className="rounded bg-[var(--bg)] border border-[var(--border)] p-3 max-h-96 overflow-y-auto">
                    <DiffViewer diff={diff.diff} />
                  </div>
                </>
              ) : (
                <p className="text-sm text-[var(--muted)] italic">
                  {!diff.available
                    ? "Not available — session was not in a git repo or start SHA was not captured."
                    : "No code changes detected in this session."}
                </p>
              )
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default function SessionsPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--muted)] py-12 text-center">
          Loading…
        </div>
      }
    >
      <SessionDetailInner />
    </Suspense>
  );
}
