import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getPipelineStatus, getChapters, getManuscriptSummary } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { useWebSocket } from "../hooks/useWebSocket";

const BROOKS_PHASES = ["setup", "response", "attack", "resolution"] as const;
const phaseColors: Record<string, string> = {
  setup: "bg-blue-400",
  first_plot_point: "bg-blue-500",
  response: "bg-green-400",
  first_pinch: "bg-green-500",
  midpoint: "bg-yellow-400",
  attack: "bg-orange-400",
  second_pinch: "bg-orange-500",
  second_plot_point: "bg-red-400",
  resolution: "bg-red-500",
  climax: "bg-red-600",
};

export default function Dashboard() {
  const { connected } = useWebSocket();

  const status = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: getPipelineStatus,
    refetchInterval: 2000,
  });

  const chapters = useQuery({
    queryKey: ["chapters"],
    queryFn: getChapters,
    refetchInterval: 5000,
  });

  const manuscript = useQuery({
    queryKey: ["manuscript-summary"],
    queryFn: getManuscriptSummary,
    refetchInterval: 10000,
  });

  const ps = status.data;
  const chList = chapters.data?.chapters ?? [];
  const ms = manuscript.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Dashboard</h2>
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          {connected ? "Live" : "Disconnected"}
        </div>
      </div>

      {/* Pipeline Status Card */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">Pipeline Status</h3>
          {ps && <StatusBadge state={ps.state} />}
        </div>
        {ps && (
          <>
            {ps.session_id && (
              <p className="text-xs text-gray-500 mb-2">Session: {ps.session_id}</p>
            )}
            <div className="w-full bg-gray-200 rounded-full h-3 mb-1">
              <div
                className="bg-blue-500 h-3 rounded-full transition-all"
                style={{
                  width: `${ps.total_chapters > 0 ? (ps.completed_chapters / ps.total_chapters) * 100 : 0}%`,
                }}
              />
            </div>
            <p className="text-xs text-gray-500">
              {ps.completed_chapters} / {ps.total_chapters} chapters
              {ps.current_chapter != null && ` (current: ${ps.current_chapter})`}
            </p>
            {ps.error && <p className="text-sm text-red-600 mt-2">{ps.error}</p>}
          </>
        )}
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Words" value={ms?.total_word_count?.toLocaleString() ?? "0"} />
        <StatCard label="Chapters" value={String(ms?.chapter_count ?? 0)} />
        <StatCard
          label="Gate Pass Rate"
          value={ps ? `${((ps.completed_chapters / Math.max(ps.total_chapters, 1)) * 100).toFixed(0)}%` : "--"}
        />
        <StatCard label="Status" value={ps?.state ?? "idle"} />
      </div>

      {/* Brooks Structure Progress */}
      {chList.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">Brooks Structure Progress</h3>
          <div className="flex gap-1 h-6 rounded overflow-hidden">
            {BROOKS_PHASES.map((phase) => (
              <div
                key={phase}
                className={`flex-1 ${phaseColors[phase] || "bg-gray-300"} flex items-center justify-center text-xs text-white font-medium`}
              >
                {phase}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chapter Results Table */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-4 border-b">
          <h3 className="font-semibold">Generated Chapters</h3>
        </div>
        {chList.length === 0 ? (
          <p className="p-4 text-gray-400 text-sm">No chapters generated yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="px-4 py-2">Chapter</th>
                  <th className="px-4 py-2">Scene</th>
                  <th className="px-4 py-2">Words</th>
                  <th className="px-4 py-2">Quality</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {chList.map((ch) => (
                  <tr key={`${ch.chapter_number}-${ch.scene_number}`} className="border-t hover:bg-gray-50">
                    <td className="px-4 py-2">{ch.chapter_number}</td>
                    <td className="px-4 py-2">{ch.scene_number}</td>
                    <td className="px-4 py-2">{ch.word_count.toLocaleString()}</td>
                    <td className="px-4 py-2">
                      {ch.quality_scores ? (
                        <QualityDot scores={ch.quality_scores} />
                      ) : (
                        <span className="text-gray-400">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/chapters/${ch.chapter_number}/${ch.scene_number}`}
                        className="text-blue-600 hover:underline text-xs"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}

function QualityDot({ scores }: { scores: Record<string, number> }) {
  const avg =
    Object.values(scores).reduce((a, b) => a + b, 0) / Math.max(Object.values(scores).length, 1);
  const color = avg >= 0.7 ? "text-green-600" : avg >= 0.5 ? "text-yellow-600" : "text-red-600";
  return <span className={`font-medium ${color}`}>{avg.toFixed(2)}</span>;
}
