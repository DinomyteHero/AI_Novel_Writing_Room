/** TypeScript interfaces for the read-only console API. */

export interface ChapterEntry {
  chapter_number: number;
  scene_number: number;
  word_count: number;
  path: string;
}

export interface ChapterDetail {
  chapter_number: number;
  scene_number: number;
  prose: string;
  word_count: number;
}

export interface LedgerEvent {
  id: number;
  event_type: string;
  chapter_number: number | null;
  scene_number: number | null;
  agent_role: string | null;
  payload: Record<string, unknown> | null;
  timestamp: string;
}

export interface ManuscriptSummary {
  total_word_count: number;
  chapter_count: number;
  chapters: Array<{
    chapter_number: number;
    scene_number: number;
    word_count: number;
  }>;
}

export interface HealthResponse {
  status: string;
  deployment_mode: string;
  phase: number;
  pipeline_state: string;
}
