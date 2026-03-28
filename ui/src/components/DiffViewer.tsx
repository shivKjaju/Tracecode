"use client";

/**
 * DiffViewer — renders a unified diff with line-level coloring.
 */

interface Props {
  diff: string;
}

export function DiffViewer({ diff }: Props) {
  if (!diff.trim()) {
    return (
      <p className="text-sm text-[var(--muted)] italic py-4">No diff available.</p>
    );
  }

  const lines = diff.split("\n");

  return (
    <pre className="text-xs font-mono overflow-x-auto leading-relaxed">
      {lines.map((line, i) => {
        let cls = "text-[var(--muted)]";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "text-[var(--success)] bg-[#1c3a28]/40";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "text-[var(--fail)] bg-[#3a1a1a]/40";
        else if (line.startsWith("@@")) cls = "text-[var(--accent)]";
        else if (line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++")) {
          cls = "text-[var(--text)] font-semibold";
        }
        return (
          <div key={i} className={`px-2 ${cls}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
