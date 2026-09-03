import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AnnouncementDialog } from "@/components/announcements/AnnouncementDialog";
import { Button } from "@/components/ui/button";
import { useChangelog } from "@/hooks/useSettings";

const CHANGELOG_URL = "https://github.com/Morelitea/initiative/blob/main/CHANGELOG.md";

interface UpdateAnnouncementDialogProps {
  open: boolean;
  version: string;
  onClose: () => void;
  /**
   * Override the reload action. Defaults to a plain page reload (web); the
   * native OTA flow swaps in the downloaded Capacitor bundle first.
   */
  onReload?: () => void;
}

/**
 * "A newer version is running on the server" — an announcement the client
 * writes for itself.
 *
 * It renders through the same dialog as every server-side notice, and differs
 * only in where its content comes from (the release's changelog entry) and in
 * offering an action beyond acknowledging it.
 */
export const UpdateAnnouncementDialog = ({
  open,
  version,
  onClose,
  onReload,
}: UpdateAnnouncementDialogProps) => {
  const { t } = useTranslation("announcements");
  const { data } = useChangelog({ version }, { enabled: open && Boolean(version) });

  const entry = data?.entries?.[0];
  const body = entry?.changes?.trim() ? entry.changes : t("update.noDetailedChanges");

  return (
    <AnnouncementDialog
      open={open}
      title={t("update.title", { version })}
      category="release"
      sections={[{ heading: t("update.whatsNew"), body }]}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      footer={
        <>
          <Button variant="ghost" size="sm" asChild>
            <a
              href={CHANGELOG_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1"
            >
              {t("update.viewAllChanges")}
              <ExternalLink className="h-3 w-3" />
            </a>
          </Button>
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose}>
            {t("update.later")}
          </Button>
          <Button onClick={() => (onReload ? onReload() : window.location.reload())}>
            {t("update.reloadNow")}
          </Button>
        </>
      }
    />
  );
};
