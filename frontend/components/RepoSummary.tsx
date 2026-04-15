import { ScanAnalysis } from "@/lib/api";

export function RepoSummary({ analysis }: { analysis: ScanAnalysis }) {
  return (
    <div className="border border-gray-800 rounded-lg p-5 space-y-4 bg-gray-900">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Repo Summary</h2>

      <div>
        <p className="text-white leading-relaxed">{analysis.what_it_does}</p>
      </div>

      {analysis.use_case && (
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Use Case</div>
          <p className="text-gray-300 text-sm">{analysis.use_case}</p>
        </div>
      )}

      {analysis.tech_stack && analysis.tech_stack.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Tech Stack</div>
          <div className="flex flex-wrap gap-2">
            {analysis.tech_stack.map((t) => (
              <span
                key={t}
                className="text-sm bg-gray-800 text-gray-300 px-3 py-1 rounded-full border border-gray-700"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {analysis.caveats && analysis.caveats.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Caveats</div>
          <ul className="space-y-1">
            {analysis.caveats.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-yellow-400">
                <span className="mt-0.5">⚠</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
