import type { Confidence, DocumentStatus } from "../types";

export function StatusBadge({ status, label }: { status: DocumentStatus; label?: string }) {
  return <span className={`status-badge ${status}`}>{label ?? status}</span>;
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`confidence-badge ${confidence}`}>{confidence} confidence</span>;
}
