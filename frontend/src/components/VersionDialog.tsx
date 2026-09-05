import { CheckCircle2, Download, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useChangelog } from "@/hooks/useSettings";
import { cn } from "@/lib/utils";

/**
 * What version this is, and what has changed lately — opened from the sidebar.
 *
 * The other half of this dialog used to be the "a newer version is running on
 * the server" prompt. That is an announcement, and now renders as one (see
 * ``components/announcements/UpdateAnnouncementDialog``); what is left here is
 * the reference panel a person opens on purpose.
 */
interface VersionDialogProps {
  children?: React.ReactNode;
  currentVersion: string;
  latestVersion?: string | null;
  hasUpdate?: boolean;
  isLoadingVersion?: boolean;
}

export const VersionDialog = ({
  children,
  currentVersion,
  latestVersion,
  hasUpdate = false,
  isLoadingVersion = false,
}: VersionDialogProps) => {
  const { t } = useTranslation("guilds");

  const { data, isLoading } = useChangelog({ limit: 20 });

  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="flex h-[80vh] flex-col gap-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle>{t("version.versionInformation")}</DialogTitle>
          <DialogDescription>{t("version.currentVersionAndChangelog")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
          <div className="shrink-0 space-y-4 border-b pb-4">
            {hasUpdate && (
              <div className="flex items-center gap-1.5 font-medium text-primary text-sm">
                <Download className="h-4 w-4" />
                <span>{t("version.updateAvailable")}</span>
              </div>
            )}
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">{t("version.currentVersion")}</span>
                <span className="font-medium font-mono">v{currentVersion}</span>
              </div>
              {isLoadingVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className="text-muted-foreground">{t("version.latestVersionLoading")}</span>
                </div>
              ) : latestVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className={cn("font-medium font-mono", hasUpdate && "text-primary")}>
                    v{latestVersion}
                  </span>
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className="text-muted-foreground text-xs">
                    {t("version.latestVersionUnavailable")}
                  </span>
                </div>
              )}
            </div>
            {!hasUpdate && latestVersion && (
              <div className="flex items-center gap-1.5 text-green-600 text-sm dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                <span>{t("version.upToDate")}</span>
              </div>
            )}
            {hasUpdate && (
              <p className="text-muted-foreground text-sm">
                {t("version.newVersionOnDockerHub")}{" "}
                <a
                  href="https://hub.docker.com/r/morelitea/initiative"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  Docker Hub
                </a>
              </p>
            )}
          </div>

          {/* Changelog Section */}
          <div className="flex min-h-0 flex-1 flex-col">
            <h3 className="mb-3 shrink-0 font-semibold text-lg">{t("version.changelog")}</h3>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : data?.entries && data.entries.length > 0 ? (
              <ScrollArea className="flex-1">
                <div className="space-y-6 pr-6">
                  {data.entries.map((entry, entryIdx) => (
                    <div key={entry.version} className={entryIdx > 0 ? "border-t pt-6" : ""}>
                      <div className="mb-4 border-b pb-2">
                        <div className="flex items-center gap-2">
                          <h4 className="font-semibold text-base">
                            {t("version.version", { version: entry.version })}
                          </h4>
                          <Badge variant="outline" className="text-xs">
                            {entry.date}
                          </Badge>
                        </div>
                      </div>
                      {entry.changes.trim() ? (
                        <Markdown content={entry.changes} />
                      ) : (
                        <p className="text-muted-foreground text-sm">
                          {t("version.noDetailedChanges")}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-muted-foreground text-sm">{t("version.noChangelog")}</p>
            )}
            <div className="shrink-0 border-t pt-3">
              <Button variant="outline" size="sm" className="w-full" asChild>
                <a
                  href="https://github.com/Morelitea/initiative/blob/main/CHANGELOG.md"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2"
                >
                  {t("version.viewAllChanges")}
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
