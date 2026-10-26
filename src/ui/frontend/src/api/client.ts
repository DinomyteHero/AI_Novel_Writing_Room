/** Typed client for the read-only writers' room console. */

import type {
  ChapterDetail,
  ChapterEntry,
  HealthResponse,
  LedgerEvent,
  ManuscriptSummary,
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

export const getHealth = () => fetchJSON<HealthResponse>("/health");

export const getChapters = () =>
  fetchJSON<{ chapters: ChapterEntry[] }>("/chapters");

export const getChapter = (ch: number, sc: number) =>
  fetchJSON<ChapterDetail>(`/chapters/${ch}/${sc}`);

export const getManuscriptSummary = () =>
  fetchJSON<ManuscriptSummary>("/manuscript/summary");

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
