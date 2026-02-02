import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Check, Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import type { GenerateDocumentSummaryResponse } from "@/types/api";

interface DocumentSummaryProps {
  documentId: number;
  summary: string | null;
  onSummaryChange: (summary: string | null) => void;
}

export const DocumentSummary = ({ documentId, summary, onSummaryChange }: DocumentSummaryProps) => {
  const { isEnabled, isLoading: isLoadingAI } = useAIEnabled();
  const [copied, setCopied] = useState(false);

  const generateSummary = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<GenerateDocumentSummaryResponse>(
        `/documents/${documentId}/ai/summary`
      );
      return response.data;
    },
    onSuccess: (data) => {
      onSummaryChange(data.summary);
    },
  });

  const handleCopy = async () => {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summary);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  const getErrorMessage = (): string | null => {
    if (!generateSummary.isError) return null;
    const error = generateSummary.error;
    if (isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      if (typeof detail === "string") return detail;
    }
    return "Failed to generate summary. Please try again.";
  };

  // Loading AI settings
  if (isLoadingAI) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  // AI not enabled
  if (!isEnabled) {
    return (
      <div className="space-y-2 py-4 text-center">
        <Sparkles className="text-muted-foreground mx-auto h-8 w-8" />
        <p className="text-muted-foreground text-sm">
          AI features are not enabled. Configure AI settings to generate document summaries.
        </p>
      </div>
    );
  }

  // No summary yet
  if (!summary && !generateSummary.isPending) {
    return (
      <div className="space-y-4 py-4 text-center">
        <Sparkles className="text-muted-foreground mx-auto h-8 w-8" />
        <p className="text-muted-foreground text-sm">
          Generate an AI-powered summary of this document.
        </p>
        <Button onClick={() => generateSummary.mutate()} disabled={generateSummary.isPending}>
          <Sparkles className="mr-2 h-4 w-4" />
          Generate Summary
        </Button>
        {generateSummary.isError && <p className="text-destructive text-sm">{getErrorMessage()}</p>}
      </div>
    );
  }

  // Generating summary
  if (generateSummary.isPending) {
    return (
      <div className="space-y-4 py-8 text-center">
        <Loader2 className="text-muted-foreground mx-auto h-8 w-8 animate-spin" />
        <p className="text-muted-foreground text-sm">Generating summary...</p>
      </div>
    );
  }

  // Summary generated
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">AI Summary</h4>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleCopy}
            title="Copy summary"
          >
            {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => generateSummary.mutate()}
            disabled={generateSummary.isPending}
            title="Regenerate summary"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <div className="bg-muted/50 rounded-lg p-4">
        <p className="text-sm whitespace-pre-wrap">{summary}</p>
      </div>
      {generateSummary.isError && <p className="text-destructive text-sm">{getErrorMessage()}</p>}
    </div>
  );
};
