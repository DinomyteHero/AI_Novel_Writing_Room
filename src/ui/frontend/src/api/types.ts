/** TypeScript interfaces matching all backend API response shapes. */

export interface PipelineStatus {
  state: "idle" | "running" | "paused" | "milestone_pending" | "completed" | "failed";
  session_id: string | null;
  current_chapter: number | null;
  total_chapters: number;
  completed_chapters: number;
  error: string | null;
  milestone_info: MilestoneInfo | null;
}

export interface MilestoneInfo {
  milestone_name: string;
  structural_phase: string;
  chapter_number: number;
  constraints: string[];
}

export interface ChapterEntry {
  chapter_number: number;
  scene_number: number;
  word_count: number;
  path: string;
  quality_scores?: Record<string, number>;
}

export interface ChapterDetail {
  chapter_number: number;
  scene_number: number;
  prose: string;
  word_count: number;
}

export interface ChapterResult {
  chapter_number: number;
  scene_number: number;
  word_count: number;
  output_path: string;
  evaluation: {
    verdict: string;
    structural_score?: number;
    voice_score?: number;
    polish_score?: number;
    failure_codes?: Array<{ code: string; description: string }>;
  };
  quality_metrics?: {
    overall_score: number;
    passed: boolean;
    repetition: Record<string, unknown>;
    pacing: Record<string, unknown>;
    voice: Record<string, unknown>;
    slop: Record<string, unknown>;
    flags: string[];
  };
  judge_evaluation?: {
    overall_score: number;
    dimensions?: Record<string, number>;
    feedback?: string;
  };
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

export interface SceneCard {
  chapter_number: number;
  scene_number: number;
  structural_phase: string;
  pov_character: string;
  mission: string;
  conflict: string;
  turning_point: string;
  characters_present?: string[];
  setting?: string;
  target_word_count?: number;
}

export interface Character {
  id: string;
  name: string;
  current_location?: string;
  emotional_state?: string;
  arc_position?: string;
  inventory?: string;
  relationships?: Relationship[];
  knowledge?: KnowledgeEntry[];
}

export interface Relationship {
  character_a: string;
  character_b: string;
  relationship_type: string;
  status: string;
}

export interface KnowledgeEntry {
  character_id: string;
  fact_id: string;
  fact_description: string;
  layer: string;
  is_accurate: boolean;
  acquired_chapter?: number;
}

export interface PlotThread {
  id: string;
  description: string;
  status: string;
  planted_chapter: number;
  urgency: string;
  related_characters?: string;
}

export interface Session {
  session_id: string;
  created_at: string;
  updated_at: string;
  completed_count: number;
  total_cards: number;
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

export interface LedgerSummary {
  total_events: number;
  events_by_type: Record<string, number>;
  gate_pass_count: number;
  gate_fail_count: number;
  gate_pass_rate: number | null;
}

export interface HealthResponse {
  status: string;
  deployment_mode: string;
  phase: number;
  pipeline_state: string;
}
