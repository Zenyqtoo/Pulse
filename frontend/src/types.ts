export interface User { id: number; login: string; full_name: string; role: 'admin' | 'operator' | 'viewer'; department_code: string | null; active: boolean }

export interface Enrichment {
  departments: string[]; primary_department: string; dept_confidence: number
  sentiment: string; sentiment_score: number; sentiment_confidence: number; message_type: string
  district: string | null; address: string | null; object: string | null; problem_type: string | null
  urgency_markers: string[]; is_urgent: boolean; rationale: string; model: string; prompt_version: string
  latency_ms: number | null; needs_review: boolean; reviewed: boolean; reviewed_at: string | null
  model_department: string | null; model_sentiment: string | null; corrected: boolean
}

export interface Item {
  id: number; source_id: number; source_name: string; source_type: string; is_synthetic: boolean
  url: string | null; text: string; lang: string | null; published_at: string; collected_at: string | null
  author: string | null; reactions: number; replies: number; views: number
  is_direct: boolean; is_spam: boolean; spam_reason: string | null; duplicate_of_id: number | null
  status: string; process_state: string; pii_found: string[]
  enrichment: Enrichment | null
  cluster: { id: number; title: string; priority: string } | null
  similarity?: number
  platform: string; kind: string; parent_url: string | null
  geo_status: 'local' | 'possible' | 'not_local'; geo_reason: string | null; geo_reviewed: boolean
}

export interface ItemDetail extends Item {
  process_error: string | null; can_reply: boolean; can_view_original: boolean
  corrections: { field: string; old: string | null; new: string; comment: string | null; at: string }[]
  gold: { department: string; sentiment: string; split: string } | null
  geo_evidence: Record<string, unknown>; geo_score: number; parent_external_id: string | null
  context_text: string | null; geo_llm: string | null; place_mentioned: string | null
}

export interface PriorityTerm { label: string; value: string | number; points: number; max: number }

export interface Cluster {
  id: number; title: string; summary: string; summary_model: string | null; department: string; department_name: string
  district: string | null; item_count: number; count_24h: number; count_prev_24h: number; growth_rate: number
  neg_share: number; reach: number; has_urgent: boolean; priority: 'high' | 'medium' | 'low'; priority_score: number
  priority_factors: { terms: Record<string, PriorityTerm>; score: number; thresholds: { high: number; medium: number }; forced_by_life_threat: boolean }
  status: string; status_changed_at: string | null; first_seen: string | null; last_seen: string | null; active: boolean; is_hot: boolean
  platforms: string[]; source_count: number; multi_platform: boolean
}

export interface ClusterDetail extends Cluster {
  items: Item[]; hidden_direct: number; timeline: { date: string; count: number }[]
  copies: { id: number; duplicate_of_id: number; platform: string; url: string | null; source_name: string | null; published_at: string }[]
}

export interface Meta {
  app_name: string; city_name: string
  departments: { code: string; name: string; name_kk: string | null }[]
  districts: string[]
  sources: { id: number; name: string; type: string; is_synthetic: boolean; platform: string }[]
  platforms: Record<string, string>
  llm_enabled: boolean; llm_model: string; embedding_backend: string; user: User
}

export interface Paged<T> { total: number; items: T[] }
