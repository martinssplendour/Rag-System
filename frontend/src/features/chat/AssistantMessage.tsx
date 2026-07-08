import { AlertCircle, Bot, Clipboard, XCircle } from "lucide-react";
import { useState } from "react";

import { ConfidenceBadge } from "../../components/Badges";
import { formatScore } from "../../lib/format";
import type { AnswerSource, AskResponse } from "../../types";

export function AssistantMessage({ response }: { response: AskResponse }) {
  const [copied, setCopied] = useState(false);
  const [selectedSource, setSelectedSource] = useState<AnswerSource | null>(null);

  async function copyAnswer() {
    await navigator.clipboard.writeText(response.answer);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <article className="message-row assistant-message">
      <div className="message-avatar">
        <Bot size={17} aria-hidden="true" />
      </div>
      <div className="assistant-content">
        <div className="assistant-header">
          <ConfidenceBadge confidence={response.confidence} />
          <button
            className="icon-button"
            type="button"
            onClick={() => void copyAnswer()}
            aria-label="Copy answer"
          >
            <Clipboard size={16} aria-hidden="true" />
          </button>
        </div>
        <p className="answer-text">
          {renderAnswer(response.answer, response.sources, setSelectedSource)}
        </p>
        {response.sources.length > 0 ? (
          <SourceReferenceChips sources={response.sources} onSelect={setSelectedSource} />
        ) : null}
        {response.uncertainty ? (
          <div className="uncertainty">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{response.uncertainty}</span>
          </div>
        ) : null}
        <p className="limitations">{response.limitations}</p>
        {copied ? <span className="copy-confirmation">Copied</span> : null}
      </div>
      {selectedSource ? (
        <SourceEvidenceDialog source={selectedSource} onClose={() => setSelectedSource(null)} />
      ) : null}
    </article>
  );
}

function SourceReferenceChips({
  sources,
  onSelect,
}: {
  sources: AnswerSource[];
  onSelect: (source: AnswerSource) => void;
}) {
  return (
    <div className="source-chip-row" aria-label="Answer references">
      <span>References</span>
      {sources.map((source) => (
        <button
          className="source-chip"
          key={`${source.document_id}-${source.source_id}`}
          type="button"
          onClick={() => onSelect(source)}
        >
          {source.source_id}
        </button>
      ))}
    </div>
  );
}

function SourceEvidenceDialog({
  source,
  onClose,
}: {
  source: AnswerSource;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="source-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="source-dialog-header">
          <div>
            <span className="source-dialog-label">{source.source_id}</span>
            <h3 id="source-dialog-title">{source.document_title}</h3>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="Close source evidence"
          >
            <XCircle size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="source-dialog-meta">
          <span>{formatScore(source.relevance_score)}</span>
          <span>{source.country ?? "Unknown country"}</span>
          <span>{source.language ?? "Unknown language"}</span>
          {source.page_number && source.page_number > 0 ? <span>Page {source.page_number}</span> : null}
          {source.section_title ? <span>{source.section_title}</span> : null}
        </div>
        <div className="source-dialog-body">
          <p>{source.snippet}</p>
        </div>
        <div className="source-dialog-actions">
          <button className="icon-text-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
    </div>
  );
}

function renderAnswer(
  answer: string,
  sources: AnswerSource[],
  onSourceClick: (source: AnswerSource) => void,
) {
  const sourceById = new Map(sources.map((source) => [source.source_id, source]));
  return answer.split(/(\[[^\]]+\])/g).map((part, index) => {
    const knownSourceIds = knownSourceIdsInCitation(part, sourceById);
    if (knownSourceIds.length === 0) {
      return <span key={`${part}-${index}`}>{part}</span>;
    }
    return (
      <span className="source-token-group" key={`${part}-${index}`}>
        [
        {knownSourceIds.map((sourceId, sourceIndex) => {
          const source = sourceById.get(sourceId);
          if (!source) {
            return null;
          }
          return (
            <span key={`${sourceId}-${index}`}>
              {sourceIndex > 0 ? ", " : null}
              <button
                className="source-token"
                type="button"
                onClick={() => onSourceClick(source)}
              >
                {sourceId}
              </button>
            </span>
          );
        })}
        ]
      </span>
    );
  });
}

function knownSourceIdsInCitation(
  text: string,
  sourceById: Map<string, AnswerSource>,
): string[] {
  return Array.from(sourceById.keys()).filter((sourceId) => {
    const pattern = new RegExp(`(^|[^A-Za-z0-9-])${escapeRegExp(sourceId)}([^A-Za-z0-9-]|$)`);
    return pattern.test(text);
  });
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
