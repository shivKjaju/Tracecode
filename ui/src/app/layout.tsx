import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tracecode",
  description: "Personal AI coding session quality engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <nav className="border-b border-[var(--border)] px-6 py-3 flex items-center gap-4">
          <a href="/" className="text-[var(--text)] font-semibold tracking-tight hover:text-[var(--accent)] transition-colors">
            tracecode
          </a>
          <span className="text-[var(--muted)] text-sm">session quality</span>
        </nav>
        <main className="max-w-5xl mx-auto px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
