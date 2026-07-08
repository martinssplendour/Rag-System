import { useCallback, useState } from "react";

import { ApiError, listDocuments } from "../../api";
import { errorMessage } from "../../lib/errors";
import type { DocumentItem } from "../../types";

export function useDocuments(token: string, onAuthExpired: () => void) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [documentError, setDocumentError] = useState<string | null>(null);

  const refreshDocuments = useCallback(
    async (options?: { quiet?: boolean }) => {
      if (!options?.quiet) {
        setIsLoadingDocuments(true);
      }
      setDocumentError(null);
      try {
        const response = await listDocuments(token);
        setDocuments(response.items);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          onAuthExpired();
          return;
        }
        setDocumentError(errorMessage(caught));
      } finally {
        if (!options?.quiet) {
          setIsLoadingDocuments(false);
        }
      }
    },
    [onAuthExpired, token],
  );

  return {
    documents,
    isLoadingDocuments,
    documentError,
    refreshDocuments,
  };
}
