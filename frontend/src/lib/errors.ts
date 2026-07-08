import { ApiError } from "../api";
import type { ApiErrorEnvelope } from "../types";

export function errorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    return `${friendlyErrorCode(caught.code)}${caught.message ? `: ${caught.message}` : ""}`;
  }
  if (caught instanceof Error) {
    return caught.message;
  }
  const envelope = caught as ApiErrorEnvelope;
  return envelope.error?.message || "Something went wrong.";
}

function friendlyErrorCode(code?: string): string {
  if (!code) {
    return "Request failed";
  }
  return code
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
