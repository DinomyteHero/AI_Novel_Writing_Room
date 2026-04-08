/** Typed API client for the AI Writers' Room backend. */

import type {
  PipelineStatus,
  ChapterEntry,
  ChapterDetail,
  ChapterResult,
  LedgerEvent,
  SceneCard,
  Character,
  PlotThread,
  Session,
  ManuscriptSummary,
  LedgerSummary,
  HealthResponse,
  KnowledgeEntry,
} from "./types";

const BASE = "/api";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// --- Health ---
export const getHealth = () => fetchJSON<HealthResponse>("/health");

// --- Pipeline ---
export const getPipelineStatus = () => fetchJSON<PipelineStatus>("/pipeline/status");

export const startPipeline = (opts: {
  concept_seed_path?: string;
  scene_cards_dir?: string;
  phase?: number;
  no_revision?: boolean;
  no_milestones?: boolean;
  judge?: boolean;
}) =>
  fetchJSON<{ session_id: string; status: string; total_chapters: number }>(
    "/pipeline/start",
    { method: "POST", body: JSON.stringify(opts) }
  );

export const pausePipeline = () =>
  fetchJSON<{ status: string }>("/pipeline/pause", { method: "POST" });

export const resumePipeline = () =>
  fetchJSON<{ status: string }>("/pipeline/resume", { method: "POST" });

export const getPipelineResults = () =>
  fetchJSON<{ results: ChapterResult[] }>("/pipeline/results");

export const approveMilestone = (shouldContinue: boolean) =>
  fetchJSON<{ status: string }>("/pipeline/milestone/approve", {
    method: "POST",
    body: JSON.stringify({ should_continue: shouldContinue }),
  });

// --- Chapters ---
export const getChapters = () =>
  fetchJSON<{ chapters: ChapterEntry[] }>("/chapters");

export const getChapter = (ch: number, sc: number) =>
  fetchJSON<ChapterDetail>(`/chapters/${ch}/${sc}`);

export const getChapterMetrics = (ch: number, sc: number) =>
  fetchJSON<Record<string, unknown>>(`/chapters/${ch}/${sc}/metrics`);

export const getChapterEvaluation = (ch: number, sc: number) =>
  fetchJSON<Record<string, unknown>>(`/chapters/${ch}/${sc}/evaluation`);

export const getManuscriptSummary = () =>
  fetchJSON<ManuscriptSummary>("/manuscript/summary");

export const triggerExport = (formats: string[] = ["md", "docx", "epub"]) =>
  fetchJSON<{ exports: Record<string, string | null> }>("/export", {
    method: "POST",
    body: JSON.stringify({ formats }),
  });

// --- Story State ---
export const getCharacters = () =>
  fetchJSON<{ characters: Character[] }>("/state/characters");

export const getCharacter = (id: string) =>
  fetchJSON<Character>(`/state/characters/${id}`);

export const getPlotThreads = () =>
  fetchJSON<{ plot_threads: PlotThread[] }>("/state/plot-threads");

export const getTimeline = (chapter?: number) =>
  fetchJSON<{ timeline: Record<string, unknown>[] }>(
    `/state/timeline${chapter ? `?chapter=${chapter}` : ""}`
  );

export const getChekovGuns = () =>
  fetchJSON<{ chekhov_guns: Record<string, unknown>[] }>("/state/chekhov-guns");

export const getCharacterKnowledge = (charId: string, layer?: string) =>
  fetchJSON<{ knowledge: KnowledgeEntry[] }>(
    `/state/knowledge/${charId}${layer ? `?layer=${layer}` : ""}`
  );

export const getDramaticIrony = (chapter: number = 1) =>
  fetchJSON<{ dramatic_ironies: Record<string, unknown>[] }>(
    `/state/dramatic-irony?chapter=${chapter}`
  );

// --- Scene Cards ---
export const getSceneCards = () =>
  fetchJSON<{ scene_cards: SceneCard[] }>("/scene-cards");

export const getSceneCard = (ch: number, sc: number) =>
  fetchJSON<SceneCard>(`/scene-cards/${ch}/${sc}`);

export const generateSceneCards = () =>
  fetchJSON<{ scene_cards: SceneCard[]; count: number }>("/scene-cards/generate", {
    method: "POST",
  });

export const getConceptSeed = () =>
  fetchJSON<Record<string, unknown>>("/concept-seed");

// --- Ledger ---
export const getLedgerEvents = (params?: {
  event_type?: string;
  chapter?: number;
  limit?: number;
}) => {
  const sp = new URLSearchParams();
  if (params?.event_type) sp.set("event_type", params.event_type);
  if (params?.chapter) sp.set("chapter", String(params.chapter));
  if (params?.limit) sp.set("limit", String(params.limit));
  const qs = sp.toString();
  return fetchJSON<{ events: LedgerEvent[]; count: number }>(
    `/ledger/events${qs ? `?${qs}` : ""}`
  );
};

export const getLatestEvents = (limit = 20) =>
  fetchJSON<{ events: LedgerEvent[] }>(`/ledger/events/latest?limit=${limit}`);

export const getLedgerSummary = () =>
  fetchJSON<LedgerSummary>("/ledger/summary");

// --- Sessions ---
export const getSessions = () =>
  fetchJSON<{ sessions: Session[] }>("/sessions");

export const getSession = (id: string) =>
  fetchJSON<Record<string, unknown>>(`/sessions/${id}`);

export const deleteSession = (id: string) =>
  fetchJSON<{ status: string }>(`/sessions/${id}`, { method: "DELETE" });
