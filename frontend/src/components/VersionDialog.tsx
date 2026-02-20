import { useTranslation } from "react-i18next";
import { Loader2, Download, CheckCircle2, ExternalLink } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useQuery } from "@tanstack/react-query";
import {
  getChangelogApiV1ChangelogGet,
  getGetChangelogApiV1ChangelogGetQueryKey,
} from "@/api/generated/version/version";
import { cn } from "@/lib/utils";

interface ChangelogEntry {
  version: string;
  date: string;
  changes: string;
}

interface VersionDialogProps {
  // For info mode (manual trigger)
  children?: React.ReactNode;
  currentVersion: string;
  latestVersion?: string | null;
  hasUpdate?: boolean;
  isLoadingVersion?: boolean;

  // For update notification mode (controlled)
  mode?: "info" | "update";
  open?: boolean;
  onClose?: () => void;
  newVersion?: string;
}

export const VersionDialog = ({
  children,
  currentVersion,
  latestVersion,
  hasUpdate = false,
  isLoadingVersion = false,
  mode = "info",
  open,
  onClose,
  newVersion,
}: VersionDialogProps) => {
  const { t } = useTranslation("guilds");

  // In update mode, show the new version's changelog only
  // In info mode, show last 5 versions
  const versionToShow = mode === "update" && newVersion ? newVersion : undefined;
  const limit = mode === "update" ? 1 : 5;

  const changelogParams: { version?: string; limit?: number } = {};
  if (versionToShow) {
    changelogParams.version = versionToShow;
  }
  if (mode === "info") {
    changelogParams.limit = limit;
  }

  const { data, isLoading } = useQuery<{ entries: ChangelogEntry[] }>({
    queryKey: getGetChangelogApiV1ChangelogGetQueryKey(changelogParams),
    queryFn: () =>
      getChangelogApiV1ChangelogGet(changelogParams) as unknown as Promise<{
        entries: ChangelogEntry[];
      }>,
    enabled: mode === "info" || (mode === "update" && Boolean(open)),
  });

  const handleReload = () => {
    window.location.reload();
  };

  interface ChangelogItem {
    text: string;
    children: string[];
  }

  // Parse changelog markdown into sections with nested items
  const parseChangelog = (text: string) => {
    const sections: { title: string; items: ChangelogItem[] }[] = [];
    const lines = text.split("\n");

    let currentSection: { title: string; items: ChangelogItem[] } | null = null;
    let currentItem: ChangelogItem | null = null;

    for (const line of lines) {
      const trimmed = line.trim();

      // Section headers like "### Added"
      if (trimmed.startsWith("### ")) {
        if (currentSection) {
          if (currentItem) {
            currentSection.items.push(currentItem);
            currentItem = null;
          }
          sections.push(currentSection);
        }
        currentSection = {
          title: trimmed.replace("### ", ""),
          items: [],
        };
      }
      // Nested list items (indented with spaces before "- ")
      else if (line.match(/^\s{2,}- /) && currentItem && currentSection) {
        currentItem.children.push(trimmed.replace("- ", ""));
      }
      // Top-level list items
      else if (trimmed.startsWith("- ") && currentSection) {
        if (currentItem) {
          currentSection.items.push(currentItem);
        }
        currentItem = {
          text: trimmed.replace("- ", ""),
          children: [],
        };
      }
    }

    // Don't forget the last item and section
    if (currentSection) {
      if (currentItem) {
        currentSection.items.push(currentItem);
      }
      sections.push(currentSection);
    }

    return sections;
  };

  const dialogContent = (
    <DialogContent className="flex h-[80vh] max-w-2xl flex-col gap-0">
      <DialogHeader className="shrink-0">
        <DialogTitle>
          {mode === "update" ? t("version.newVersionAvailable") : t("version.versionInformation")}
        </DialogTitle>
        <DialogDescription>
          {mode === "update"
            ? t("version.newVersionDescription", { version: newVersion })
            : t("version.currentVersionAndChangelog")}
        </DialogDescription>
      </DialogHeader>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
        {/* Version Info Section - only show in info mode */}
        {mode === "info" && (
          <div className="shrink-0 space-y-4 border-b pb-4">
            {hasUpdate && (
              <div className="text-primary flex items-center gap-1.5 text-sm font-medium">
                <Download className="h-4 w-4" />
                <span>{t("version.updateAvailable")}</span>
              </div>
            )}
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">{t("version.currentVersion")}</span>
                {/* eslint-disable-next-line i18next/no-literal-string */}
                <span className="font-mono font-medium">v{currentVersion}</span>
              </div>
              {isLoadingVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className="text-muted-foreground">{t("version.latestVersionLoading")}</span>
                </div>
              ) : latestVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  {/* eslint-disable-next-line i18next/no-literal-string */}
                  <span className={cn("font-mono font-medium", hasUpdate && "text-primary")}>
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
              <div className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                <span>{t("version.upToDate")}</span>
              </div>
            )}
            {/* eslint-disable i18next/no-literal-string */}
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
            {/* eslint-enable i18next/no-literal-string */}
          </div>
        )}

        {/* Changelog Section */}
        <div className="flex min-h-0 flex-1 flex-col">
          <h3 className="mb-3 shrink-0 text-lg font-semibold">{t("version.changelog")}</h3>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : data?.entries && data.entries.length > 0 ? (
            <ScrollArea className="flex-1">
              <div className="space-y-6 pr-6">
                {data.entries.map((entry, entryIdx) => {
                  const sections = parseChangelog(entry.changes);
                  return (
                    <div key={entry.version} className={entryIdx > 0 ? "border-t pt-6" : ""}>
                      <div className="mb-4 border-b pb-2">
                        <div className="flex items-center gap-2">
                          <h4 className="text-base font-semibold">
                            {t("version.version", { version: entry.version })}
                          </h4>
                          <Badge variant="outline" className="text-xs">
                            {entry.date}
                          </Badge>
                        </div>
                      </div>

                      {sections.length > 0 ? (
                        <div className="space-y-4">
                          {sections.map((section, idx) => (
                            <div key={idx}>
                              <h5 className="mb-2 text-sm font-semibold">{section.title}</h5>
                              <ul className="text-muted-foreground space-y-1 text-sm">
                                {section.items.map((item, itemIdx) => (
                                  <li key={itemIdx}>
                                    <div className="flex gap-2">
                                      <span className="text-primary shrink-0">•</span>
                                      <span>{item.text}</span>
                                    </div>
                                    {item.children.length > 0 && (
                                      <ul className="mt-1 ml-4 space-y-1">
                                        {item.children.map((child, childIdx) => (
                                          <li key={childIdx} className="flex gap-2">
                                            {/* eslint-disable-next-line i18next/no-literal-string */}
                                            <span className="text-muted-foreground shrink-0">
                                              ◦
                                            </span>
                                            <span>{child}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-muted-foreground text-sm">
                          {t("version.noDetailedChanges")}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          ) : (
            <p className="text-muted-foreground text-sm">{t("version.noChangelog")}</p>
          )}
          {/* View all changes link - only in info mode */}
          {mode === "info" && (
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
          )}
        </div>
      </div>

      {/* Footer with buttons - only in update mode */}
      {mode === "update" && (
        <DialogFooter className="shrink-0 border-t pt-4">
          <Button variant="ghost" size="sm" asChild>
            <a
              href="https://github.com/Morelitea/initiative/blob/main/CHANGELOG.md"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1"
            >
              {t("version.viewAllChanges")}
              <ExternalLink className="h-3 w-3" />
            </a>
          </Button>
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose}>
            {t("version.later")}
          </Button>
          <Button onClick={handleReload}>{t("version.reloadNow")}</Button>
        </DialogFooter>
      )}
    </DialogContent>
  );

  // In update mode, use controlled open/onOpenChange
  if (mode === "update") {
    return (
      <Dialog open={open} onOpenChange={onClose}>
        {dialogContent}
      </Dialog>
    );
  }

  // In info mode, use trigger-based dialog
  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      {dialogContent}
    </Dialog>
  );
};
