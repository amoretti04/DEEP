/**
 * Typed client for the DIP API.
 *
 * Types here mirror services/api/schemas.py. Keeping them hand-maintained
 * is acceptable for R1; R2 generates them from the OpenAPI spec.
 */

const DEFAULT_BASE = "/api";

export interface SourceSummary {
  source_id: string;
  name: string;
  country: string;
  language: string;
  tier: number;
  category: string;
  jurisdiction_class: string;
  connector: string;
  base_url: string;
  in_priority_scope: boolean;
  enabled: boolean;
  legal_review_verdict: string;
  release_wave: number | null;
  owner: string;
}

export interface SourceListResponse {
  items: SourceSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface CountsByDimension {
  by_country: Record<string, number>;
  by_tier: Record<string, number>;
  by_category: Record<string, number>;
  by_jurisdiction_class: Record<string, number>;
  total: number;
  in_priority_scope: number;
  enabled: number;
}

export interface EventRow {
  event_pid: string;
  proceeding_pid: string;
  event_type: string;
  occurred_at_utc: string;
  description_original: string;
  description_english: string | null;
  language_original: string | null;
}

export interface EventListResponse {
  items: EventRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface SourceListQuery {
  country?: string;
  tier?: number;
  category?: string;
  in_priority_scope?: boolean;
  enabled?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

// ── R2 types ──────────────────────────────────────────────────────
export interface SourceReferenceRow {
  record_uid: string;
  source_id: string;
  source_url: string;
  fetched_at_utc: string;
  parser_version: string;
  raw_object_key: string;
}

export interface DocumentRow {
  document_pid: string;
  proceeding_pid: string;
  title: string;
  document_type: string;
  url: string | null;
  raw_object_key: string | null;
  filed_at: string | null;
  language_original: string | null;
  page_count: number | null;
  has_translation: boolean;
}

export interface ProceedingEventWithContext {
  event_pid: string;
  event_type: string;
  occurred_at_utc: string;
  description_original: string;
  description_english: string | null;
  language_original: string | null;
}

export interface ProceedingDetail {
  proceeding_pid: string;
  company_pid: string;
  jurisdiction: string;
  court_name: string | null;
  court_case_number: string | null;
  proceeding_type: string;
  proceeding_type_original: string;
  administrator_name: string | null;
  administrator_role: string | null;
  opened_at: string | null;
  closed_at: string | null;
  status: string;
  events: ProceedingEventWithContext[];
  documents: DocumentRow[];
  source_references: SourceReferenceRow[];
}

export interface TranslateDocumentResponse {
  document_pid: string;
  source_language: string;
  target_language: string;
  translated_text: string;
  model_name: string;
  model_version: string;
  from_cache: boolean;
  character_count: number;
}

export interface UserSettingsPayload {
  translation: {
    enabled: boolean;
    default_target_language: string;
  };
  display: {
    show_low_confidence_badge: boolean;
    priority_scope_only_by_default: boolean;
  };
}

export interface UserSettingsResponse {
  user_id: string;
  settings: UserSettingsPayload;
  updated_at: string;
}

async function request<T>(
  base: string,
  path: string,
  params?: Record<string, unknown>,
  init?: RequestInit,
): Promise<T> {
  const url = new URL(path, new URL(base, window.location.origin));
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      url.searchParams.set(k, String(v));
    }
  }
  const response = await fetch(url.toString(), init);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listSources: (query: SourceListQuery = {}, base = DEFAULT_BASE) =>
    request<SourceListResponse>(base, "sources", query),
  sourceCounts: (base = DEFAULT_BASE) =>
    request<CountsByDimension>(base, "sources/counts"),
  listEvents: (params: { event_type?: string; limit?: number } = {}, base = DEFAULT_BASE) =>
    request<EventListResponse>(base, "events", params),

  // R2
  getProceeding: (pid: string, base = DEFAULT_BASE) =>
    request<ProceedingDetail>(base, `proceedings/${encodeURIComponent(pid)}`),
  translateDocument: (
    pid: string,
    target_language = "en",
    base = DEFAULT_BASE,
  ) =>
    request<TranslateDocumentResponse>(base, `documents/${encodeURIComponent(pid)}/translate`, undefined, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_language }),
    }),
  getSettings: (base = DEFAULT_BASE) => request<UserSettingsResponse>(base, "settings"),
  updateSettings: (payload: UserSettingsPayload, base = DEFAULT_BASE) =>
    request<UserSettingsResponse>(base, "settings", undefined, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};
