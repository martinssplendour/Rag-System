import type {
  ApiErrorEnvelope,
  AskPayload,
  AskResponse,
  DocumentListResponse,
  DocumentItem,
  TokenResponse,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;

  constructor(message: string, status: number, code = "REQUEST_FAILED", requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw await buildApiError(response);
  }

  return (await response.json()) as T;
}

async function buildApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    const error = body.error;
    return new ApiError(
      error?.message || "Request failed.",
      response.status,
      error?.code,
      error?.request_id,
    );
  } catch {
    return new ApiError("Request failed.", response.status);
  }
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function listDocuments(token: string): Promise<DocumentListResponse> {
  return requestJson<DocumentListResponse>("/documents", {}, token);
}

export async function uploadDocument(token: string, formData: FormData): Promise<DocumentItem> {
  return requestJson<DocumentItem>(
    "/documents",
    {
      method: "POST",
      body: formData,
    },
    token,
  );
}

export async function askQuestion(token: string, payload: AskPayload): Promise<AskResponse> {
  return requestJson<AskResponse>(
    "/ask",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}
