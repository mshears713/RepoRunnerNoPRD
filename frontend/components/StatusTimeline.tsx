"use client";

import { ScanStatus, ScanTimeline } from "@/lib/api";

interface Step {
  key: keyof ScanTimeline;
  label: string;
}

const STEPS: Step[] = [
  { key: "forked_at", label: "Forked" },
  { key: "codespace_ready_at", label: "Codespace Ready" },
  { key: "started_at", label: "App Started" },
  { key: "finished_at", label: "Done" },
];

function formatTime(iso?: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface Props {
  timeline: ScanTimeline;
  status: ScanStatus;
}

export function StatusTimeline({ timeline, status }: Props) {
  const failedIndex =
    status === "failed"
      ? STEPS.findLastIndex((s) => timeline[s.key])
      : -1;

  return (
    <div className="flex items-start gap-0">
      {STEPS.map((step, i) => {
        const done = Boolean(timeline[step.key]);
        const isFailed = failedIndex === i && status === "failed";
        const isActive =
          !done && status === "running" && i === STEPS.findIndex((s) => !timeline[s.key]);

        let dotClass = "w-4 h-4 rounded-full border-2 flex-shrink-0 ";
        if (isFailed) dotClass += "bg-red-500 border-red-400";
        else if (done) dotClass += "bg-green-500 border-green-400";
        else if (isActive) dotClass += "bg-blue-500 border-blue-400 animate-pulse";
        else dotClass += "bg-gray-700 border-gray-600";

        return (
          <div key={step.key} className="flex items-start flex-1">
            <div className="flex flex-col items-center">
              <div className={dotClass} />
              {i < STEPS.length - 1 && (
                <div className={`w-0.5 h-6 ${done ? "bg-green-600" : "bg-gray-700"}`} />
              )}
            </div>
            <div className="ml-3 pb-6">
              <div
                className={`text-sm font-medium ${
                  isFailed
                    ? "text-red-400"
                    : done
                    ? "text-green-300"
                    : isActive
                    ? "text-blue-300"
                    : "text-gray-500"
                }`}
              >
                {step.label}
                {isFailed && <span className="ml-1 text-red-400">failed</span>}
              </div>
              {timeline[step.key] && (
                <div className="text-xs text-gray-500 mt-0.5">{formatTime(timeline[step.key])}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
