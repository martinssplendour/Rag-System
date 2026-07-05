export type DocumentStatus = "processing" | "ready" | "failed";
export type Confidence = "high" | "medium" | "low";

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  workspace_id: string;
  is_admin: boolean;
}

export interface AuthSession {
  accessToken: string;
  workspaceId: string;
  email: string;
  isAdmin: boolean;
}

export interface DocumentItem {
  document_id: string;
  external_document_id: string | null;
  title: string;
  filename: string | null;
  country: string | null;
  language: string;
  status: DocumentStatus;
  chunk_count: number;
  created_at: string;
  technology_type: string | null;
}

export interface DocumentListResponse {
  items: DocumentItem[];
  total: number;
}

export interface AskPayload {
  question: string;
  country?: string;
  document_ids?: string[];
}

export interface AnswerSource {
  source_id: string;
  document_id: string;
  external_document_id: string | null;
  document_title: string;
  country: string | null;
  language: string | null;
  section_title: string | null;
  page_number: number | null;
  snippet: string;
  relevance_score: number;
}

export interface AskResponse {
  answer: string;
  sources: AnswerSource[];
  confidence: Confidence;
  uncertainty: string | null;
  limitations: string;
}

export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    details?: unknown;
  };
}
