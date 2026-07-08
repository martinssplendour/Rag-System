import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { ApiError, askQuestion } from "../../api";
import { errorMessage } from "../../lib/errors";
import type { AuthSession } from "../../types";
import {
  clearChatHistory,
  readChatHistory,
  writeChatHistory,
  type ChatMessage,
} from "./history";

export interface ChatSessionState {
  messages: ChatMessage[];
  question: string;
  setQuestion: Dispatch<SetStateAction<string>>;
  country: string;
  setCountry: Dispatch<SetStateAction<string>>;
  error: string | null;
  isSubmitting: boolean;
  canSubmit: boolean;
  canRestart: boolean;
  submitQuestion: () => Promise<void>;
  restartConversation: () => void;
}

export function useChatSession(
  session: AuthSession,
  onAuthExpired: () => void,
): ChatSessionState {
  const [messages, setMessages] = useState<ChatMessage[]>(() => readChatHistory(session));
  const [question, setQuestion] = useState("");
  const [country, setCountry] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canSubmit = question.trim().length >= 3 && !isSubmitting;
  const canRestart = messages.length > 0 || question.trim().length > 0 || country.length > 0;

  useEffect(() => {
    setMessages(readChatHistory(session));
    setQuestion("");
    setCountry("");
    setError(null);
    setIsSubmitting(false);
  }, [session.email, session.workspaceId]);

  useEffect(() => {
    writeChatHistory(session, messages);
  }, [messages, session]);

  const submitQuestion = useCallback(async () => {
    if (!canSubmit) {
      return;
    }

    const trimmedQuestion = question.trim();
    const selectedCountry = country.trim() || undefined;
    setError(null);
    setMessages((current) => [
      ...current,
      { id: makeId(), role: "user", content: trimmedQuestion },
    ]);
    setQuestion("");
    setIsSubmitting(true);

    try {
      const response = await askQuestion(session.accessToken, {
        question: trimmedQuestion,
        country: selectedCountry,
      });
      setMessages((current) => [...current, { id: makeId(), role: "assistant", response }]);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
        return;
      }
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }, [canSubmit, country, onAuthExpired, question, session.accessToken]);

  const restartConversation = useCallback(() => {
    clearChatHistory(session);
    setMessages([]);
    setQuestion("");
    setCountry("");
    setError(null);
  }, [session]);

  return {
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
  };
}

function makeId(): string {
  return crypto.randomUUID();
}
