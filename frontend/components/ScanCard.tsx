import Link from "next/link";
import { Scan, ScanStatus } from "@/lib/api";

const STATUS_STYLES: Record<ScanStatus, string> = {
  pending: "bg-gray-700 text-gray-300",
  running: "bg-blue-900 text-blue-300 animate-pulse",
  completed: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function ScanCard({ scan }: { scan: Scan }) {
  return (
    <Link href={`/scan/${scan.id}`} className="block">
      <div className="border border-gray-800 rounded-lg p-4 hover:border-gray-600 transition bg-gray-900 hover:bg-gray-800">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-white font-semibold truncate">
                {scan.repo_owner}/{scan.repo_name}
              </span>
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[scan.status]}`}
              >
                {scan.status}
              </span>
            </div>

            {scan.analysis?.what_it_does ? (
              <p className="text-gray-400 text-sm mt-1 line-clamp-2">
                {scan.analysis.what_it_does}
              </p>
            ) : scan.input_metadata?.summary ? (
              <p className="text-gray-500 text-sm mt-1 line-clamp-2 italic">
                {scan.input_metadata.summary}
              </p>
            ) : (
              <p className="text-gray-600 text-sm mt-1 italic">No summary yet</p>
            )}

            {scan.analysis?.tech_stack && scan.analysis.tech_stack.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {scan.analysis.tech_stack.slice(0, 5).map((t) => (
                  <span
                    key={t}
                    className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded border border-gray-700"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="text-right text-xs text-gray-500 shrink-0">
            <div>{timeAgo(scan.created_at)}</div>
            {scan.preview_url && (
              <div className="text-green-500 mt-1">live preview</div>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
