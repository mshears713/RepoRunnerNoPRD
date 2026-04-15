"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getScan, Scan } from "@/lib/api";
import { useJobStream } from "@/hooks/useJobStream";
import { StatusTimeline } from "@/components/StatusTimeline";
import { PreviewPanel } from "@/components/PreviewPanel";
import { RepoSummary } from "@/components/RepoSummary";
import { FailureInsight } from "@/components/FailureInsight";

export default function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [initialScan, setInitialScan] = useState<Scan | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getScan(id)
      .then(setInitialScan)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const { scan, connected } = useJobStream(id, initialScan);
  const current = scan ?? initialScan;

  if (loading) {
    return <div className="text-center text-gray-500 py-12">Loading...</div>;
  }

  if (!current) {
    return <div className="text-center text-red-400 py-12">Scan not found.</div>;
  }

  const isTerminal = current.status === "completed" || current.status === "failed";

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <a
            href={current.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xl font-bold text-white hover:text-blue-400 transition"
          >
            {current.repo_owner}/{current.repo_name}
          </a>
          <div className="text-sm text-gray-500 mt-1">
            Submitted {new Date(current.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {!isTerminal && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${connected ? "text-green-400" : "text-gray-500"}`}>
              {connected ? "live" : "reconnecting..."}
            </span>
          )}
          <StatusBadge status={current.status} />
        </div>
      </div>

      {/* Status Timeline */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
          Status Timeline
        </h2>
        <StatusTimeline timeline={current.timeline} status={current.status} />
      </section>

      {/* Live Preview */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
          Live Preview
        </h2>
        <PreviewPanel previewUrl={current.preview_url} status={current.status} />
      </section>

      {/* Repo Summary */}
      {current.analysis && (
        <section>
          <RepoSummary analysis={current.analysis} />
        </section>
      )}

      {/* Failure Insight */}
      {current.failure && current.status === "failed" && (
        <section>
          <FailureInsight failure={current.failure} />
        </section>
      )}

      {/* Raw execution info (collapsible) */}
      {current.execution && (
        <details className="border border-gray-800 rounded-lg">
          <summary className="px-4 py-3 text-sm text-gray-400 cursor-pointer hover:text-white">
            Execution Details
          </summary>
          <div className="px-4 pb-4 space-y-3">
            <div className="text-xs text-gray-500">
              Duration: {current.execution.duration_sec?.toFixed(1)}s |{" "}
              Exit code: {current.execution.exit_code} |{" "}
              Stage reached: {current.execution.stage_reached}
            </div>
            {current.execution.stdout_tail && (
              <div>
                <div className="text-xs text-gray-600 mb-1">stdout</div>
                <pre className="bg-gray-950 rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-48 overflow-y-auto">
                  {current.execution.stdout_tail}
                </pre>
              </div>
            )}
            {current.execution.stderr_tail && (
              <div>
                <div className="text-xs text-gray-600 mb-1">stderr</div>
                <pre className="bg-gray-950 rounded p-3 text-xs text-red-300 overflow-x-auto max-h-48 overflow-y-auto">
                  {current.execution.stderr_tail}
                </pre>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-gray-700 text-gray-300",
    running: "bg-blue-900 text-blue-300 animate-pulse",
    completed: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
  };
  return (
    <span className={`text-sm px-3 py-1 rounded-full font-medium ${styles[status] ?? "bg-gray-700 text-gray-300"}`}>
      {status}
    </span>
  );
}
