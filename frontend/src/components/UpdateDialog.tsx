import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";

interface ChangelogEntry {
  version: string;
  date: string;
  changes: string;
}

interface UpdateDialogProps {
  open: boolean;
  newVersion: string;
  onClose: () => void;
}

export const UpdateDialog = ({ open, newVersion, onClose }: UpdateDialogProps) => {
  const { data, isLoading } = useQuery<{ entries: ChangelogEntry[] }>({
    queryKey: ["changelog", newVersion],
    queryFn: async () => {
      const response = await apiClient.get("/changelog", {
        params: { version: newVersion },
      });
      return response.data;
    },
    enabled: open,
  });

  const handleReload = () => {
    window.location.reload();
  };

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
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New Version Available</DialogTitle>
          <DialogDescription>
            Version {newVersion} is now available. Reload to update.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : changelog ? (
            <div className="space-y-4">
              <div className="border-b pb-2">
                <h3 className="text-lg font-semibold">Version {changelog.version}</h3>
                <p className="text-muted-foreground text-sm">{changelog.date}</p>
              </div>

              {sections.length > 0 ? (
                <div className="space-y-4">
                  {sections.map((section, idx) => (
                    <div key={idx}>
                      <h4 className="mb-2 text-sm font-semibold">{section.title}</h4>
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

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Later
          </Button>
          <Button onClick={handleReload}>Reload Now</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
