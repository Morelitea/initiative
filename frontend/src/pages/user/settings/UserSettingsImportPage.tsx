import { useState } from "react";
import { useTranslation } from "react-i18next";

import asanaIcon from "@/assets/asana.png";
import ticktickIcon from "@/assets/ticktick.svg";
import todoistIcon from "@/assets/todoist.svg";
import trelloIcon from "@/assets/trello.svg";
import vikunjaIcon from "@/assets/vikunja.svg";
import { TickTickImportDialog } from "@/components/import/TickTickImportDialog";
import { TodoistImportDialog } from "@/components/import/TodoistImportDialog";
import { VikunjaImportDialog } from "@/components/import/VikunjaImportDialog";
import { SettingsSection } from "@/components/settings/SettingsSection";

interface ImportPlatform {
  id: string;
  name: string;
  descriptionKey: string;
  icon: string;
  available: boolean;
}

const IMPORT_PLATFORMS: ImportPlatform[] = [
  {
    id: "todoist",
    name: "Todoist",
    descriptionKey: "page.platforms.todoist",
    icon: todoistIcon,
    available: true,
  },
  {
    id: "ticktick",
    name: "TickTick",
    descriptionKey: "page.platforms.ticktick",
    icon: ticktickIcon,
    available: true,
  },
  {
    id: "vikunja",
    name: "Vikunja",
    descriptionKey: "page.platforms.vikunja",
    icon: vikunjaIcon,
    available: true,
  },
  {
    id: "trello",
    name: "Trello",
    descriptionKey: "page.platforms.trello",
    icon: trelloIcon,
    available: false,
  },
  {
    id: "asana",
    name: "Asana",
    descriptionKey: "page.platforms.asana",
    icon: asanaIcon,
    available: false,
  },
];

export const UserSettingsImportPage = () => {
  const { t } = useTranslation("import");
  const [ticktickDialogOpen, setTicktickDialogOpen] = useState(false);
  const [todoistDialogOpen, setTodoistDialogOpen] = useState(false);
  const [vikunjaDialogOpen, setVikunjaDialogOpen] = useState(false);

  const handlePlatformClick = (platform: ImportPlatform) => {
    if (!platform.available) return;

    switch (platform.id) {
      case "ticktick":
        setTicktickDialogOpen(true);
        break;
      case "todoist":
        setTodoistDialogOpen(true);
        break;
      case "vikunja":
        setVikunjaDialogOpen(true);
        break;
      default:
        break;
    }
  };

  return (
    <>
      <SettingsSection title={t("page.title")} description={t("page.description")}>
        <div className="grid gap-4 sm:grid-cols-2">
          {IMPORT_PLATFORMS.map((platform) => (
            <button
              key={platform.id}
              type="button"
              onClick={() => handlePlatformClick(platform)}
              disabled={!platform.available}
              className={`relative flex items-start gap-4 rounded-lg border p-4 text-left transition-colors ${
                platform.available
                  ? "cursor-pointer hover:border-primary hover:bg-accent"
                  : "cursor-not-allowed opacity-60"
              }`}
            >
              <img src={platform.icon} alt={platform.name} className="h-8 w-8" />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium">{platform.name}</h3>
                  {!platform.available && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground text-xs">
                      {t("page.comingSoon")}
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground text-sm">
                  {t(platform.descriptionKey as never)}
                </p>
              </div>
            </button>
          ))}
        </div>
      </SettingsSection>

      <TickTickImportDialog open={ticktickDialogOpen} onOpenChange={setTicktickDialogOpen} />
      <TodoistImportDialog open={todoistDialogOpen} onOpenChange={setTodoistDialogOpen} />
      <VikunjaImportDialog open={vikunjaDialogOpen} onOpenChange={setVikunjaDialogOpen} />
    </>
  );
};
