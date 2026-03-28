"use client";

import type { FileTouch } from "@/lib/api";

interface Props {
  touches: FileTouch[];
}

function persistedLabel(p: number | null): string {
  if (p === 1) return "✓";
  if (p === 0) return "✗";
  return "·";
}

function persistedClass(p: number | null): string {
  if (p === 1) return "text-[var(--success)]";
  if (p === 0) return "text-[var(--fail)]";
  return "text-[var(--muted)]";
}

export function FileTouchTable({ touches }: Props) {
  if (touches.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)] italic py-4">No file touches recorded.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-[var(--muted)]">
            <th className="text-left font-normal py-2 pr-4">file</th>
            <th className="text-right font-normal py-2 pr-4 w-16">touches</th>
            <th className="text-center font-normal py-2 w-16">persisted</th>
          </tr>
        </thead>
        <tbody>
          {touches.map((t) => (
            <tr
              key={t.id}
              className="border-b border-[var(--border)]/50 hover:bg-[var(--surface)] transition-colors"
            >
              <td className="py-1.5 pr-4">
                <span className={`font-mono text-xs ${t.is_hot ? "text-[var(--partial)]" : "text-[var(--text)]"}`}>
                  {t.file_path}
                </span>
                {t.is_hot && (
                  <span className="ml-2 text-xs text-[var(--partial)] opacity-70">hot</span>
                )}
              </td>
              <td className="py-1.5 pr-4 text-right font-mono text-[var(--muted)]">
                {t.touch_count}
              </td>
              <td className={`py-1.5 text-center font-mono ${persistedClass(t.persisted)}`}>
                {persistedLabel(t.persisted)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
