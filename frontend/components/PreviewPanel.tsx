"use client";

import { ScanStatus } from "@/lib/api";

interface Props {
  previewUrl?: string;
  status: ScanStatus;
}

export function PreviewPanel({ previewUrl, status }: Props) {
  if (status === "failed") {
    return (
      <div className="border border-gray-800 rounded-lg p-6 text-center text-gray-500">
        No preview available — app did not start successfully.
      </div>
    );
  }

  if (status === "running" || status === "pending") {
    return (
      <div className="border border-gray-800 rounded-lg p-6 flex items-center justify-center gap-3 text-gray-400">
        <span className="inline-block w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        Waiting for app to start...
      </div>
    );
  }

  if (!previewUrl) {
    return (
      <div className="border border-gray-800 rounded-lg p-6 text-center text-gray-500">
        No preview URL captured. App may have started on a non-standard port
        or not exposed any HTTP interface.
      </div>
    );
  }

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <div className="bg-gray-800 px-4 py-2 text-xs text-gray-400 flex items-center justify-between">
        <span>Live Preview — running in Codespace</span>
        <a
          href={previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300"
        >
          Open in new tab
        </a>
      </div>
      <iframe
        src={previewUrl}
        className="w-full h-96 bg-white"
        title="Live repo preview"
        sandbox="allow-scripts allow-same-origin allow-forms"
      />
    </div>
  );
}
