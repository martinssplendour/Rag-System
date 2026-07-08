import type { AskResponse, AuthSession } from "../../types";

export type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; response: AskResponse };

const CHAT_HISTORY_PREFIX = "kintiga.chat.session";

export function readChatHistory(session: AuthSession): ChatMessage[] {
  try {
    const raw = window.sessionStorage.getItem(chatHistoryKey(session));
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    const messages = Array.isArray(parsed) ? parsed : isRecord(parsed) ? parsed.messages : null;
    if (!Array.isArray(messages)) {
      return [];
    }
    return messages.filter(isChatMessage);
  } catch {
    return [];
  }
}

export function writeChatHistory(session: AuthSession, messages: ChatMessage[]): void {
  try {
    const key = chatHistoryKey(session);
    if (messages.length === 0) {
      window.sessionStorage.removeItem(key);
      return;
    }
    window.sessionStorage.setItem(key, JSON.stringify({ messages }));
  } catch {
    // Chat history is convenience state; failed browser storage should not block chat.
  }
}

export function clearChatHistory(session: AuthSession): void {
  try {
    window.sessionStorage.removeItem(chatHistoryKey(session));
  } catch {
    // Ignore storage failures during logout/restart.
  }
}

function chatHistoryKey(session: AuthSession): string {
  return `${CHAT_HISTORY_PREFIX}.${session.workspaceId}.${session.email.toLowerCase()}`;
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (!isRecord(value) || typeof value.id !== "string") {
    return false;
  }
  if (value.role === "user") {
    return typeof value.content === "string";
  }
  if (value.role === "assistant") {
    return isAskResponse(value.response);
  }
  return false;
}

function isAskResponse(value: unknown): value is AskResponse {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.answer === "string" &&
    Array.isArray(value.sources) &&
    (value.confidence === "high" || value.confidence === "medium" || value.confidence === "low") &&
    (typeof value.uncertainty === "string" || value.uncertainty === null) &&
    typeof value.limitations === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
