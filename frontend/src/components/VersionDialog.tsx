import { Loader2, Download, CheckCircle2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { cn } from "@/lib/utils";

interface ChangelogEntry {
  version: string;
  date: string;
  changes: string;
}

interface VersionDialogProps {
  currentVersion: string;
  latestVersion: string | null;
  hasUpdate: boolean;
  isLoadingVersion: boolean;
  children: React.ReactNode;
}

export const VersionDialog = ({
  currentVersion,
  latestVersion,
  hasUpdate,
  isLoadingVersion,
  children,
}: VersionDialogProps) => {
  const { data, isLoading } = useQuery<{ entries: ChangelogEntry[] }>({
    queryKey: ["changelog", currentVersion],
    queryFn: async () => {
      const response = await apiClient.get("/changelog", {
        params: { version: currentVersion },
      });
      return response.data;
    },
  });

  const changelog = data?.entries?.[0];

  // Parse changelog markdown into sections
  const parseChangelog = (text: string) => {
    const sections: { title: string; items: string[] }[] = [];
    const lines = text.split("\n");

    let currentSection: { title: string; items: string[] } | null = null;

    for (const line of lines) {
      const trimmed = line.trim();

      // Section headers like "### Added"
      if (trimmed.startsWith("### ")) {
        if (currentSection) {
          sections.push(currentSection);
        }
        currentSection = {
          title: trimmed.replace("### ", ""),
          items: [],
        };
      }
      // List items
      else if (trimmed.startsWith("- ") && currentSection) {
        currentSection.items.push(trimmed.replace("- ", ""));
      }
    }

    if (currentSection) {
      sections.push(currentSection);
    }

    return sections;
  };

  const sections = changelog ? parseChangelog(changelog.changes) : [];

  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Version Information</DialogTitle>
          <DialogDescription>Current version and changelog</DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {/* Version Info Section */}
          <div className="space-y-4 border-b pb-4">
            {hasUpdate && (
              <div className="text-primary flex items-center gap-1.5 text-sm font-medium">
                <Download className="h-4 w-4" />
                <span>Update available</span>
              </div>
            )}
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Current version:</span>
                <span className="font-mono font-medium">v{currentVersion}</span>
              </div>
              {isLoadingVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Latest version:</span>
                  <span className="text-muted-foreground">Loading...</span>
                </div>
              ) : latestVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Latest version:</span>
                  <span className={cn("font-mono font-medium", hasUpdate && "text-primary")}>
                    v{latestVersion}
                  </span>
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Latest version:</span>
                  <span className="text-muted-foreground text-xs">Unavailable</span>
                </div>
              )}
            </div>
            {!hasUpdate && latestVersion && (
              <div className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                <span>Up to date</span>
              </div>
            )}
            {hasUpdate && (
              <p className="text-muted-foreground text-sm">
                A new version is available on{" "}
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
          <div>
            <h3 className="mb-4 text-lg font-semibold">Changelog</h3>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : changelog ? (
              <div className="space-y-4">
                <div className="border-b pb-2">
                  <div className="flex items-center gap-2">
                    <h4 className="text-base font-semibold">Version {changelog.version}</h4>
                    <Badge variant="outline" className="text-xs">
                      {changelog.date}
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
                            <li key={itemIdx} className="flex gap-2">
                              <span className="text-primary">•</span>
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm">No detailed changes available.</p>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                No changelog available for this version.
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
