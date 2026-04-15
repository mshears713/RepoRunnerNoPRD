import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Repo Viability Scanner",
  description: "Is this repo worth your time?",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen font-mono">
        <header className="border-b border-gray-800 px-6 py-4">
          <a href="/" className="text-lg font-bold text-white hover:text-gray-300">
            Repo Viability Scanner
          </a>
          <a
            href="/submit"
            className="ml-6 text-sm text-gray-400 hover:text-white transition"
          >
            + Submit Repo
          </a>
        </header>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
