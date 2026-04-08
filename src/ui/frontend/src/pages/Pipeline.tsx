import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPipelineStatus,
  startPipeline,
  pausePipeline,
  resumePipeline,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";
import EventLog from "../components/EventLog";
import MilestoneModal from "../components/MilestoneModal";
import { useWebSocket } from "../hooks/useWebSocket";

export default function Pipeline() {
  const queryClient = useQueryClient();
  const { events, connected, clearEvents } = useWebSocket();
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [conceptSeed, setConceptSeed] = useState("");
  const [sceneCardsDir, setSceneCardsDir] = useState("");
  const [phase, setPhase] = useState(4);
  const [noRevision, setNoRevision] = useState(false);
  const [noMilestones, setNoMilestones] = useState(false);
  const [judge, setJudge] = useState(false);

  const status = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: getPipelineStatus,
    refetchInterval: 1000,
  });

  const ps = status.data;

  const handleStart = async () => {
    setError(null);
    clearEvents();
    try {
      await startPipeline({
        concept_seed_path: conceptSeed || undefined,
        scene_cards_dir: sceneCardsDir || undefined,
        phase,
        no_revision: noRevision,
        no_milestones: noMilestones,
        judge,
      });
      queryClient.invalidateQueries({ queryKey: ["pipeline-status"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start pipeline");
    }
  };

  const handlePause = async () => {
    try {
      await pausePipeline();
      queryClient.invalidateQueries({ queryKey: ["pipeline-status"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to pause");
    }
  };

  const handleResume = async () => {
    try {
      await resumePipeline();
      queryClient.invalidateQueries({ queryKey: ["pipeline-status"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to resume");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Pipeline Control</h2>
        <div className="flex items-center gap-2">
          {ps && <StatusBadge state={ps.state} />}
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
        </div>
      </div>

      {/* Start Form */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Start Pipeline</h3>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Concept Seed Path</label>
            <input
              type="text"
              value={conceptSeed}
              onChange={(e) => setConceptSeed(e.target.value)}
              placeholder="Leave blank to use server default"
              className="w-full border rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Scene Cards Directory</label>
            <input
              type="text"
              value={sceneCardsDir}
              onChange={(e) => setSceneCardsDir(e.target.value)}
              placeholder="Leave blank to use server default"
              className="w-full border rounded px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <div className="flex items-center gap-6 mb-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Phase</label>
            <select
              value={phase}
              onChange={(e) => setPhase(Number(e.target.value))}
              className="border rounded px-2 py-1.5 text-sm"
            >
              {[1, 2, 3, 4].map((p) => (
                <option key={p} value={p}>Phase {p}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={noRevision} onChange={(e) => setNoRevision(e.target.checked)} />
            Skip Revision
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={noMilestones} onChange={(e) => setNoMilestones(e.target.checked)} />
            Skip Milestones
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} />
            LLM Judge
          </label>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleStart}
            disabled={ps?.state === "running"}
            className="px-4 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Start Pipeline
          </button>
          {ps?.state === "running" && (
            <button
              onClick={handlePause}
              className="px-4 py-2 text-sm rounded bg-yellow-500 text-white hover:bg-yellow-600"
            >
              Pause
            </button>
          )}
          {ps?.state === "paused" && (
            <button
              onClick={handleResume}
              className="px-4 py-2 text-sm rounded bg-green-600 text-white hover:bg-green-700"
            >
              Resume
            </button>
          )}
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>

      {/* Current Chapter */}
      {ps?.state === "running" && ps.current_chapter != null && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-1">Current Chapter</h3>
          <p className="text-sm text-gray-600">
            Processing chapter {ps.current_chapter}...
            ({ps.completed_chapters} / {ps.total_chapters} complete)
          </p>
        </div>
      )}

      {/* Live Activity Log */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold">Live Activity Log</h3>
          <button
            onClick={clearEvents}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        </div>
        <EventLog events={events} />
      </div>

      {/* Milestone Modal */}
      {ps?.state === "milestone_pending" && ps.milestone_info && (
        <MilestoneModal
          milestone={ps.milestone_info}
          onResolved={() => queryClient.invalidateQueries({ queryKey: ["pipeline-status"] })}
        />
      )}
    </div>
  );
}
