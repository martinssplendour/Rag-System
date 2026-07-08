import {
  Bot,
  FileText,
  Globe2,
  MessageSquareText,
  Paperclip,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  User,
} from "lucide-react";
import type { FormEvent } from "react";

import { InlineAlert } from "../../components/InlineAlert";
import { COUNTRY_OPTIONS } from "../../constants/options";
import { normalisePastedQuestionText } from "../../lib/questionText";
import type { DocumentItem } from "../../types";
import { AssistantMessage } from "./AssistantMessage";
import type { ChatSessionState } from "./useChatSession";

export function EvidenceChat({
  documents,
  chat,
}: {
  documents: DocumentItem[];
  chat: ChatSessionState;
}) {
  const {
    messages,
    question,
    setQuestion,
    country,
    setCountry,
    error,
    isSubmitting,
    canSubmit,
    canRestart,
    submitQuestion,
    restartConversation,
  } = chat;
  const readyDocuments = documents.filter((document) => document.status === "ready");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitQuestion();
  }

  return (
    <section className="chat-page" aria-labelledby="chat-title">
      <div className="chat-scope-toolbar" aria-label="Ask filters">
        <label className="scope-control">
          <Globe2 size={19} aria-hidden="true" />
          <select value={country} onChange={(event) => setCountry(event.target.value)}>
            <option value="">All countries</option>
            {COUNTRY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="scope-control readonly">
          <FileText size={19} aria-hidden="true" />
          <span>{readyDocuments.length} ready documents</span>
        </div>
        <button
          className="icon-text-button"
          type="button"
          onClick={() => {
            setCountry("");
          }}
        >
          <SlidersHorizontal size={18} aria-hidden="true" />
          Filters
        </button>
        <button
          className="icon-text-button"
          type="button"
          onClick={restartConversation}
          disabled={!canRestart || isSubmitting}
        >
          <RotateCcw size={18} aria-hidden="true" />
          Restart
        </button>
      </div>

      <div className="chat-main panel">
        <div className="message-stream" aria-live="polite">
          {messages.length === 0 ? (
            <div className="chat-empty-state">
              <div className="chat-empty-icon" aria-hidden="true">
                <MessageSquareText size={34} />
              </div>
              <h3 id="chat-title">Ask anything about your evidence</h3>
              <p>Answers include confidence, limitations, and source snippets.</p>
            </div>
          ) : null}
          {messages.map((message) =>
            message.role === "user" ? (
              <article key={message.id} className="message-row user-message">
                <div className="message-avatar">
                  <User size={17} aria-hidden="true" />
                </div>
                <p>{message.content}</p>
              </article>
            ) : (
              <AssistantMessage key={message.id} response={message.response} />
            ),
          )}
          {isSubmitting ? (
            <article className="message-row assistant-message pending">
              <div className="message-avatar">
                <Bot size={17} aria-hidden="true" />
              </div>
              <p>Retrieving evidence and drafting answer...</p>
            </article>
          ) : null}
        </div>

        {error ? <InlineAlert tone="error" message={error} /> : null}

        <form className="ask-form" onSubmit={handleSubmit}>
          <div className="ask-input-shell">
            <button className="icon-button attach-button" type="button" disabled aria-label="Attach file">
              <Paperclip size={20} aria-hidden="true" />
            </button>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onPaste={(event) => {
                event.preventDefault();
                const pasted = normalisePastedQuestionText(event.clipboardData.getData("text"));
                const target = event.currentTarget;
                const start = target.selectionStart;
                const end = target.selectionEnd;
                setQuestion((current) => `${current.slice(0, start)}${pasted}${current.slice(end)}`);
              }}
              placeholder="Ask a market-access question"
              rows={1}
            />
            <button className="primary-button ask-submit-button" type="submit" disabled={!canSubmit}>
              <Sparkles size={20} aria-hidden="true" />
              {isSubmitting ? "Asking..." : "Ask"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
