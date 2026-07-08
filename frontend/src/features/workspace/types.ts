export type View = "chat" | "upload" | "documents";

export function viewTitle(view: View): string {
  if (view === "chat") {
    return "Evidence Chat";
  }
  if (view === "upload") {
    return "Upload Evidence";
  }
  return "Document Library";
}

export function viewSubtitle(view: View): string {
  if (view === "chat") {
    return "Ask questions and get answers across your uploaded evidence.";
  }
  if (view === "upload") {
    return "Add source documents for grounded market-access retrieval.";
  }
  return "Review uploaded documents, processing state, and source metadata.";
}
