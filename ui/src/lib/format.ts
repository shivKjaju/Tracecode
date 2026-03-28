/**
 * format.ts — Formatting helpers used across UI components.
 */

/** Format a Unix second timestamp as "Mar 26 14:02" */
export function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Format duration in seconds as "1h 23m" or "45m" or "12s" */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
}

/** Shorten a git SHA to 8 chars */
export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 8) : "—";
}

/** Format a 0-1 float as a percentage string "72%" */
export function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

/** Count added/removed lines in a unified diff string */
export function diffStats(diff: string): { added: number; removed: number; files: number } {
  let added = 0, removed = 0;
  const files = new Set<string>();
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) added++;
    else if (line.startsWith("-") && !line.startsWith("---")) removed++;
    else if (line.startsWith("+++ ")) files.add(line.slice(4));
  }
  return { added, removed, files: files.size };
}
