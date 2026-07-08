import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { AnswerSource, AskResponse, DocumentItem } from "./types";

const SESSION_STORAGE_KEY = "kintiga.auth.session";

describe("App", () => {
  it("signs in and renders the workspace shell", async () => {
    const fetchMock = mockApi();

    render(<App />);

    await userEvent.type(screen.getByLabelText(/email/i), "analyst@example.com");
    await userEvent.type(screen.getByPlaceholderText("Your password"), "secure-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("analyst@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /logout/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows admin-only upload controls for country and language", async () => {
    seedSession({ isAdmin: true });
    mockApi({ documents: [readyDocument()] });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: /upload evidence/i }));

    expect(screen.getByRole("heading", { name: "Upload evidence" })).toBeInTheDocument();
    expect(screen.getByLabelText("Country")).toHaveDisplayValue("Select country");
    expect(screen.getByLabelText("Language")).toHaveDisplayValue("Auto detect");
    expect(screen.getByText("Automatic language detection")).toBeInTheDocument();
  });

  it("asks a question, renders permanent citations, and opens source evidence", async () => {
    seedSession({ isAdmin: true });
    mockApi({
      documents: [readyDocument()],
      askResponse: answerWithSource(),
    });

    render(<App />);

    await screen.findByText("1 ready documents");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a market-access question"),
      "What were the main evidence gaps?",
    );
    await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(await screen.findByText(/Immature survival data/)).toBeInTheDocument();

    const citationButtons = await screen.findAllByRole("button", { name: "UK-NICE-001" });
    await userEvent.click(citationButtons[0]);

    const dialog = await screen.findByRole("dialog", {
      name: "UK NICE Oncology Drug Summary",
    });
    expect(within(dialog).getByText("UK-NICE-001")).toBeInTheDocument();
    expect(within(dialog).getByText("81% relevance")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Immature overall survival data and limited real-world evidence/),
    ).toBeInTheDocument();
  });

  it("keeps the chat transcript when switching views and clears it on restart", async () => {
    seedSession({ isAdmin: true });
    mockApi({
      documents: [readyDocument()],
      askResponse: answerWithSource(),
    });

    render(<App />);

    await screen.findByText("1 ready documents");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a market-access question"),
      "What were the main evidence gaps?",
    );
    await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(await screen.findByText(/Immature survival data/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /upload evidence/i }));
    expect(screen.getByRole("heading", { name: "Upload evidence" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /evidence chat/i }));
    expect(screen.getByText("What were the main evidence gaps?")).toBeInTheDocument();
    expect(screen.getByText(/Immature survival data/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /restart/i }));
    expect(screen.getByText("Ask anything about your evidence")).toBeInTheDocument();
    expect(screen.queryByText(/Immature survival data/)).not.toBeInTheDocument();
  });

  it("keeps a pending chat response when switching away from chat", async () => {
    seedSession({ isAdmin: true });
    const pendingAnswer = createDeferred<AskResponse>();
    mockApi({
      documents: [readyDocument()],
      askResponse: pendingAnswer.promise,
    });

    render(<App />);

    await screen.findByText("1 ready documents");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a market-access question"),
      "What were the main evidence gaps?",
    );
    await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));
    expect(await screen.findByText("Retrieving evidence and drafting answer...")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /upload evidence/i }));
    expect(screen.getByRole("heading", { name: "Upload evidence" })).toBeInTheDocument();

    pendingAnswer.resolve(answerWithSource());

    await waitFor(() => {
      expect(window.sessionStorage.getItem("kintiga.chat.session.workspace-a.analyst@example.com"))
        .toContain("Immature survival data");
    });

    await userEvent.click(screen.getByRole("button", { name: /evidence chat/i }));
    expect(screen.getByText("What were the main evidence gaps?")).toBeInTheDocument();
    expect(screen.getByText(/Immature survival data/)).toBeInTheDocument();
  });

  it("clears session chat history on logout", async () => {
    seedSession({ isAdmin: true });
    mockApi({
      documents: [readyDocument()],
      askResponse: answerWithSource(),
    });

    render(<App />);

    await screen.findByText("1 ready documents");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a market-access question"),
      "What were the main evidence gaps?",
    );
    await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(await screen.findByText(/Immature survival data/)).toBeInTheDocument();
    expect(window.sessionStorage.length).toBe(1);

    await userEvent.click(screen.getByRole("button", { name: /logout/i }));
    expect(window.sessionStorage.length).toBe(0);
  });

  it("allows admin users to delete documents from the library", async () => {
    seedSession({ isAdmin: true });
    const fetchMock = mockApi({ documents: [readyDocument()] });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: /document library/i }));
    await userEvent.click(await screen.findByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/documents/doc-uk",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("hides upload and delete actions from non-admin users", async () => {
    seedSession({ isAdmin: false });
    mockApi({ documents: [readyDocument()] });

    render(<App />);

    expect(screen.queryByRole("button", { name: /upload evidence/i })).not.toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: /document library/i }));
    expect(await screen.findByText("UK NICE Oncology Drug Summary")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });
});

function seedSession({ isAdmin }: { isAdmin: boolean }) {
  window.localStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      accessToken: "test-token",
      workspaceId: "workspace-a",
      email: "analyst@example.com",
      isAdmin,
    }),
  );
}

function mockApi({
  documents = [],
  askResponse = answerWithSource(),
}: {
  documents?: DocumentItem[];
  askResponse?: AskResponse | Promise<AskResponse>;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url === "/api/auth/login" && method === "POST") {
      return jsonResponse({
        access_token: "test-token",
        token_type: "bearer",
        expires_in: 3600,
        workspace_id: "workspace-a",
        is_admin: true,
      });
    }

    if (url === "/api/documents" && method === "GET") {
      return jsonResponse({ items: documents, total: documents.length });
    }

    if (url === "/api/ask" && method === "POST") {
      return jsonResponse(await askResponse);
    }

    if (url === "/api/documents/doc-uk" && method === "DELETE") {
      return jsonResponse({ document_id: "doc-uk", status: "deleted" });
    }

    return jsonResponse(
      {
        error: {
          code: "NOT_FOUND",
          message: `Unhandled test request: ${method} ${url}`,
        },
      },
      404,
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function readyDocument(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    document_id: "doc-uk",
    external_document_id: "uk_nice_oncology_drug_summary",
    citation_prefix: "UK-NICE",
    title: "UK NICE Oncology Drug Summary",
    filename: "uk_nice_oncology_drug_summary.txt",
    country: "United Kingdom",
    language: "en",
    status: "ready",
    chunk_count: 11,
    created_at: "2026-07-05T12:00:00Z",
    ...overrides,
  };
}

function answerWithSource(): AskResponse {
  const source: AnswerSource = {
    source_id: "UK-NICE-001",
    document_id: "doc-uk",
    external_document_id: "uk_nice_oncology_drug_summary",
    document_title: "UK NICE Oncology Drug Summary",
    country: "United Kingdom",
    language: "en",
    section_title: "Evidence gaps and uncertainty",
    page_number: 1,
    snippet: "Immature overall survival data and limited real-world evidence were highlighted.",
    relevance_score: 0.81,
  };

  return {
    answer: "Immature survival data was the main evidence gap [UK-NICE-001].",
    sources: [source],
    confidence: "high",
    uncertainty: "Evidence is limited to uploaded documents.",
    limitations:
      "This response is based only on the uploaded market-access documents and is not medical, legal, regulatory, reimbursement, or pricing advice.",
  };
}
