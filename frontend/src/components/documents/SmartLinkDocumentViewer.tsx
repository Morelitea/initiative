import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";

export interface SmartLinkContent {
  url: string;
}

export interface SmartLinkDocumentViewerProps {
  content: SmartLinkContent | null | undefined;
  className?: string;
}

export function SmartLinkDocumentViewer({ content, className }: SmartLinkDocumentViewerProps) {
  const { t } = useTranslation("documents");
  const url = content?.url ?? "";
  const match = useMemo(() => matchSmartLinkProvider(url), [url]);
  const ProviderIcon = match.icon;

  if (!url) {
    return (
      <div
        className={cn(
          "bg-background text-muted-foreground flex h-64 w-full items-center justify-center rounded-lg border shadow",
          className
        )}
      >
        {t("smartLink.missingUrl")}
      </div>
    );
  }

  if (match.canEmbed && match.embedSrc) {
    return (
      <div
        className={cn(
          "bg-background relative h-[80vh] w-full overflow-hidden rounded-lg border shadow",
          className
        )}
      >
        <iframe
          src={match.embedSrc}
          className="h-full w-full border-0"
          title={url}
          allow={match.iframeAttrs.allow}
          referrerPolicy={match.iframeAttrs.referrerPolicy}
          allowFullScreen
        />
      </div>
    );
  }

  // Unknown / non-embeddable provider — link card.
  return (
    <div
      className={cn(
        "bg-background flex w-full flex-col items-start gap-3 rounded-lg border p-6 shadow",
        className
      )}
    >
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <ProviderIcon className="h-4 w-4" />
        <span>{match.label}</span>
      </div>
      <div className="text-sm font-medium break-all">{url}</div>
      <p className="text-muted-foreground text-xs">
        {match.embedHintKey ? t(match.embedHintKey) : t("smartLink.unsupportedProvider")}
      </p>
      <Button asChild variant="default" size="sm">
        <a href={url} target="_blank" rel="noopener noreferrer">
          <ExternalLink className="mr-2 h-4 w-4" />
          {t("smartLink.openInNewTab")}
        </a>
      </Button>
    </div>
  );
}
