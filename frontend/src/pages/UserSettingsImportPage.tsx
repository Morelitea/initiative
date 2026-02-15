import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Upload } from "lucide-react";

import asanaIcon from "@/assets/asana.png";
import ticktickIcon from "@/assets/ticktick.svg";
import todoistIcon from "@/assets/todoist.svg";
import trelloIcon from "@/assets/trello.svg";
import vikunjaIcon from "@/assets/vikunja.svg";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TickTickImportDialog } from "@/components/import/TickTickImportDialog";
import { TodoistImportDialog } from "@/components/import/TodoistImportDialog";
import { VikunjaImportDialog } from "@/components/import/VikunjaImportDialog";

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
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            {t("page.title")}
          </CardTitle>
          <CardDescription>{t("page.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2">
            {IMPORT_PLATFORMS.map((platform) => (
              <button
                key={platform.id}
                type="button"
                onClick={() => handlePlatformClick(platform)}
                disabled={!platform.available}
                className={`relative flex items-start gap-4 rounded-lg border p-4 text-left transition-colors ${
                  platform.available
                    ? "hover:bg-accent hover:border-primary cursor-pointer"
                    : "cursor-not-allowed opacity-60"
                }`}
              >
                <img src={platform.icon} alt={platform.name} className="h-8 w-8" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium">{platform.name}</h3>
                    {!platform.available && (
                      <span className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-xs">
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
        </CardContent>
      </Card>

      <TickTickImportDialog open={ticktickDialogOpen} onOpenChange={setTicktickDialogOpen} />
      <TodoistImportDialog open={todoistDialogOpen} onOpenChange={setTodoistDialogOpen} />
      <VikunjaImportDialog open={vikunjaDialogOpen} onOpenChange={setVikunjaDialogOpen} />
    </>
  );
};
