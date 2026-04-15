import { ScanFailure } from "@/lib/api";

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  missing_env_vars: { label: "Missing Environment Variables", color: "text-yellow-400 bg-yellow-900/40 border-yellow-800" },
  bad_deps: { label: "Dependency Installation Failed", color: "text-orange-400 bg-orange-900/40 border-orange-800" },
  runtime_crash: { label: "Runtime Crash", color: "text-red-400 bg-red-900/40 border-red-800" },
  timeout: { label: "Execution Timeout", color: "text-purple-400 bg-purple-900/40 border-purple-800" },
  port_conflict: { label: "Port Conflict", color: "text-blue-400 bg-blue-900/40 border-blue-800" },
  build_failure: { label: "Build Failed", color: "text-orange-400 bg-orange-900/40 border-orange-800" },
  unknown: { label: "Unknown Error", color: "text-gray-400 bg-gray-800 border-gray-700" },
};

export function FailureInsight({ failure }: { failure: ScanFailure }) {
  const cat = CATEGORY_LABELS[failure.category] ?? CATEGORY_LABELS.unknown;

  return (
    <div className="border border-red-900 rounded-lg p-5 space-y-4 bg-red-950/30">
      <h2 className="text-sm font-semibold text-red-400 uppercase tracking-wider">Failure Insight</h2>

      <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm border ${cat.color}`}>
        {cat.label}
      </div>

      <p className="text-gray-300 text-sm leading-relaxed">{failure.plain_explanation}</p>

      {failure.fix_suggestions && failure.fix_suggestions.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Suggested Fixes</div>
          <ol className="space-y-1">
            {failure.fix_suggestions.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                <span className="text-gray-500 shrink-0">{i + 1}.</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
