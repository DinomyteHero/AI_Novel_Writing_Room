import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar,
} from "recharts";
import { getPipelineResults, getLedgerSummary } from "../api/client";

export default function Quality() {
  const resultsQ = useQuery({
    queryKey: ["pipeline-results"],
    queryFn: getPipelineResults,
    refetchInterval: 5000,
  });

  const summaryQ = useQuery({
    queryKey: ["ledger-summary"],
    queryFn: getLedgerSummary,
  });

  const results = resultsQ.data?.results ?? [];
  const summary = summaryQ.data;

  // Build chart data from results
  const scoreData = results
    .filter((r) => r.quality_metrics)
    .map((r) => ({
      chapter: `Ch${r.chapter_number}`,
      overall: r.quality_metrics!.overall_score,
      repetition: (r.quality_metrics!.repetition as Record<string, number>)?.repetition_score ?? 0,
      pacing: (r.quality_metrics!.pacing as Record<string, number>)?.pacing_score ?? 0,
      voice: (r.quality_metrics!.voice as Record<string, number>)?.voice_fidelity_score ?? 0,
      slop: (r.quality_metrics!.slop as Record<string, number>)?.slop_score ?? 0,
    }));

  // Failure codes frequency
  const failureFreq: Record<string, number> = {};
  for (const r of results) {
    for (const fc of r.evaluation?.failure_codes ?? []) {
      const code = typeof fc === "string" ? fc : fc.code;
      failureFreq[code] = (failureFreq[code] ?? 0) + 1;
    }
  }
  const failureData = Object.entries(failureFreq)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([code, count]) => ({ code, count }));

  // Worst chapters
  const worstChapters = results
    .filter((r) => r.quality_metrics && !r.quality_metrics.passed)
    .sort((a, b) => (a.quality_metrics?.overall_score ?? 1) - (b.quality_metrics?.overall_score ?? 1));

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Quality Dashboard</h2>

      {/* Score Trends */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Quality Score Trends</h3>
        {scoreData.length === 0 ? (
          <p className="text-gray-400 text-sm">No quality data available yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={scoreData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="chapter" />
              <YAxis domain={[0, 1]} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="overall" stroke="#3b82f6" strokeWidth={2} name="Overall" />
              <Line type="monotone" dataKey="repetition" stroke="#ef4444" name="Repetition" />
              <Line type="monotone" dataKey="pacing" stroke="#22c55e" name="Pacing" />
              <Line type="monotone" dataKey="voice" stroke="#a855f7" name="Voice" />
              <Line type="monotone" dataKey="slop" stroke="#f59e0b" name="Slop" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Failure Code Frequency */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Failure Code Frequency</h3>
        {failureData.length === 0 ? (
          <p className="text-gray-400 text-sm">No failure codes recorded.</p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={failureData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="code" angle={-30} textAnchor="end" height={80} fontSize={11} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Worst Chapters */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">Chapters Below Threshold</h3>
          {worstChapters.length === 0 ? (
            <p className="text-gray-400 text-sm">All chapters above threshold.</p>
          ) : (
            <ul className="text-sm space-y-2">
              {worstChapters.map((r) => (
                <li key={`${r.chapter_number}-${r.scene_number}`} className="flex justify-between">
                  <span>Chapter {r.chapter_number}.{r.scene_number}</span>
                  <span className="text-red-600 font-medium">
                    {r.quality_metrics!.overall_score.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Gate Stats */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">Gate Statistics</h3>
          {summary ? (
            <div className="text-sm space-y-2">
              <div className="flex justify-between">
                <span>Total Events</span>
                <span className="font-medium">{summary.total_events}</span>
              </div>
              <div className="flex justify-between">
                <span>Gate Passes</span>
                <span className="font-medium text-green-600">{summary.gate_pass_count}</span>
              </div>
              <div className="flex justify-between">
                <span>Gate Failures</span>
                <span className="font-medium text-red-600">{summary.gate_fail_count}</span>
              </div>
              <div className="flex justify-between">
                <span>Pass Rate</span>
                <span className="font-medium">
                  {summary.gate_pass_rate != null
                    ? `${(summary.gate_pass_rate * 100).toFixed(0)}%`
                    : "--"}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-gray-400 text-sm">Loading...</p>
          )}
        </div>
      </div>
    </div>
  );
}
