"use client";

import { useState } from "react";
import useSWR from "swr";
import { listScans, Scan, ScanStatus } from "@/lib/api";
import { ScanCard } from "@/components/ScanCard";

const TABS: { label: string; status?: ScanStatus }[] = [
  { label: "All" },
  { label: "Running", status: "running" },
  { label: "Completed", status: "completed" },
  { label: "Failed", status: "failed" },
];

export default function FeedPage() {
  const [activeStatus, setActiveStatus] = useState<ScanStatus | undefined>(undefined);

  const { data, error, isLoading } = useSWR(
    ["scans", activeStatus],
    () => listScans(activeStatus, 50, 0),
    { refreshInterval: 10000 }
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-white">Recent Scans</h1>
        <a
          href="/submit"
          className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg transition"
        >
          + Submit Repo
        </a>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 mb-6 border-b border-gray-800 pb-2">
        {TABS.map((tab) => (
          <button
            key={tab.label}
            onClick={() => setActiveStatus(tab.status)}
            className={`px-4 py-1.5 rounded-md text-sm transition ${
              activeStatus === tab.status
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && (
        <div className="text-center text-gray-500 py-12">Loading...</div>
      )}

      {error && (
        <div className="text-center text-red-400 py-12">
          Failed to load scans. Is the backend running?
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="text-center text-gray-600 py-12">
          No scans yet.{" "}
          <a href="/submit" className="text-blue-400 hover:underline">
            Submit a repo to get started.
          </a>
        </div>
      )}

      {data && (
        <div className="space-y-3">
          {data.items.map((scan: Scan) => (
            <ScanCard key={scan.id} scan={scan} />
          ))}
        </div>
      )}

      {data && data.total > 50 && (
        <div className="text-center text-gray-500 text-sm mt-6">
          Showing 50 of {data.total} scans
        </div>
      )}
    </div>
  );
}
