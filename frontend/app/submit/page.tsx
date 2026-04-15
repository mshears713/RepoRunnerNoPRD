"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { submitScan } from "@/lib/api";

type Mode = "quick" | "enriched";

const SCHEMA_HINT = `{
  "repo_url": "https://github.com/owner/repo",
  "summary": "What this repo does",
  "reason_selected": "Why you're interested",
  "tags": ["python", "api"],
  "priority": "high"
}`;

export default function SubmitPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("quick");
  const [url, setUrl] = useState("");
  const [jsonInput, setJsonInput] = useState(SCHEMA_HINT);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function validateUrl(v: string): string {
    try {
      const u = new URL(v);
      if (!u.hostname.includes("github.com")) return "Must be a github.com URL";
      const parts = u.pathname.replace(/^\//, "").split("/");
      if (parts.length < 2 || !parts[1]) return "URL must include owner and repo";
      return "";
    } catch {
      return "Invalid URL";
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      let body: Parameters<typeof submitScan>[0];

      if (mode === "quick") {
        const urlErr = validateUrl(url);
        if (urlErr) { setError(urlErr); setSubmitting(false); return; }
        body = { repo_url: url };
      } else {
        try {
          body = JSON.parse(jsonInput);
        } catch {
          setError("Invalid JSON — please check your input.");
          setSubmitting(false);
          return;
        }
      }

      const result = await submitScan(body);
      router.push(`/scan/${result.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Submission failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-6">Submit a Repository</h1>

      {/* Mode toggle */}
      <div className="flex gap-1 mb-6 border border-gray-800 rounded-lg p-1 w-fit">
        <button
          onClick={() => setMode("quick")}
          className={`px-4 py-1.5 rounded-md text-sm transition ${
            mode === "quick" ? "bg-gray-700 text-white" : "text-gray-400 hover:text-white"
          }`}
        >
          Quick Submit
        </button>
        <button
          onClick={() => setMode("enriched")}
          className={`px-4 py-1.5 rounded-md text-sm transition ${
            mode === "enriched" ? "bg-gray-700 text-white" : "text-gray-400 hover:text-white"
          }`}
        >
          Enriched Submit
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {mode === "quick" ? (
          <div>
            <label className="block text-sm text-gray-400 mb-2">GitHub Repository URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 transition"
              required
            />
          </div>
        ) : (
          <div>
            <label className="block text-sm text-gray-400 mb-2">
              Enriched JSON Input
              <span className="ml-2 text-gray-600 text-xs">(from upstream agent)</span>
            </label>
            <textarea
              value={jsonInput}
              onChange={(e) => setJsonInput(e.target.value)}
              rows={10}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-blue-500 transition resize-y"
            />
          </div>
        )}

        {error && (
          <div className="text-red-400 text-sm bg-red-900/30 border border-red-800 rounded-lg px-4 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium px-6 py-2.5 rounded-lg transition"
        >
          {submitting ? "Submitting..." : "Submit"}
        </button>
      </form>
    </div>
  );
}
