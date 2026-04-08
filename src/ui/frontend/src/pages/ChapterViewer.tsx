import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getChapter, getChapterMetrics, getChapterEvaluation, getSceneCard } from "../api/client";

export default function ChapterViewer() {
  const { chapter, scene } = useParams<{ chapter: string; scene: string }>();
  const ch = Number(chapter);
  const sc = Number(scene);

  const chapterQ = useQuery({
    queryKey: ["chapter", ch, sc],
    queryFn: () => getChapter(ch, sc),
    enabled: !isNaN(ch) && !isNaN(sc),
  });

  const metricsQ = useQuery({
    queryKey: ["chapter-metrics", ch, sc],
    queryFn: () => getChapterMetrics(ch, sc),
    enabled: !isNaN(ch) && !isNaN(sc),
    retry: false,
  });

  const evalQ = useQuery({
    queryKey: ["chapter-eval", ch, sc],
    queryFn: () => getChapterEvaluation(ch, sc),
    enabled: !isNaN(ch) && !isNaN(sc),
    retry: false,
  });

  const sceneCardQ = useQuery({
    queryKey: ["scene-card", ch, sc],
    queryFn: () => getSceneCard(ch, sc),
    enabled: !isNaN(ch) && !isNaN(sc),
    retry: false,
  });

  const data = chapterQ.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="text-blue-600 hover:underline text-sm">&larr; Dashboard</Link>
        <h2 className="text-2xl font-bold">
          Chapter {ch}, Scene {sc}
        </h2>
        {data && (
          <span className="text-sm text-gray-500">{data.word_count.toLocaleString()} words</span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Prose Display */}
        <div className="col-span-2 bg-white rounded-lg shadow p-6">
          {chapterQ.isLoading && <p className="text-gray-400">Loading...</p>}
          {chapterQ.error && (
            <p className="text-red-600">Failed to load chapter: {String(chapterQ.error)}</p>
          )}
          {data && (
            <div className="prose prose-sm max-w-none">
              {data.prose.split("\n\n").map((para, i) => (
                <p key={i} className="mb-3 leading-relaxed">
                  <span className="text-xs text-gray-300 mr-2">{i + 1}</span>
                  {para}
                </p>
              ))}
            </div>
          )}
        </div>

        {/* Side Panels */}
        <div className="space-y-4">
          {/* Quality Metrics */}
          <Panel title="Quality Metrics">
            {metricsQ.isLoading && <p className="text-gray-400 text-sm">Loading...</p>}
            {metricsQ.error && <p className="text-gray-400 text-sm">Not available</p>}
            {metricsQ.data && <MetricsView data={metricsQ.data} />}
          </Panel>

          {/* Gate Evaluation */}
          <Panel title="Gate Evaluation">
            {evalQ.data?.gate_evaluation ? (
              <EvalView data={evalQ.data.gate_evaluation as Record<string, unknown>} />
            ) : (
              <p className="text-gray-400 text-sm">Not available</p>
            )}
          </Panel>

          {/* Judge Evaluation */}
          <Panel title="LLM Judge">
            {evalQ.data?.judge_evaluation ? (
              <EvalView data={evalQ.data.judge_evaluation as Record<string, unknown>} />
            ) : (
              <p className="text-gray-400 text-sm">Not available</p>
            )}
          </Panel>

          {/* Scene Card */}
          <Panel title="Scene Card">
            {sceneCardQ.data ? (
              <div className="text-sm space-y-1">
                <p><strong>Mission:</strong> {sceneCardQ.data.mission}</p>
                <p><strong>Phase:</strong> {sceneCardQ.data.structural_phase}</p>
                <p><strong>POV:</strong> {sceneCardQ.data.pov_character}</p>
                <p><strong>Conflict:</strong> {sceneCardQ.data.conflict}</p>
                <p><strong>Turning Point:</strong> {sceneCardQ.data.turning_point}</p>
              </div>
            ) : (
              <p className="text-gray-400 text-sm">Not available</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h4 className="font-semibold text-sm mb-2">{title}</h4>
      {children}
    </div>
  );
}

function MetricsView({ data }: { data: Record<string, unknown> }) {
  const scores = (data.quality_scores ?? data) as Record<string, number>;
  return (
    <div className="text-sm space-y-1">
      {Object.entries(scores).map(([key, val]) => (
        <div key={key} className="flex justify-between">
          <span className="text-gray-600">{key}</span>
          <span className="font-medium">{typeof val === "number" ? val.toFixed(2) : String(val)}</span>
        </div>
      ))}
    </div>
  );
}

function EvalView({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="text-sm space-y-1">
      {Object.entries(data).map(([key, val]) => (
        <div key={key} className="flex justify-between">
          <span className="text-gray-600">{key}</span>
          <span className="font-medium truncate ml-2">
            {typeof val === "number" ? val.toFixed(2) : Array.isArray(val) ? `[${val.length}]` : String(val)}
          </span>
        </div>
      ))}
    </div>
  );
}
