import { useTranslation } from "react-i18next";

import { NODE_TYPE_CONFIGS } from "./types";

export function NodePalette() {
  const { t } = useTranslation("automations");

  return (
    <div className="bg-card/50 w-56 shrink-0 overflow-y-auto border-r p-4">
      <h2 className="text-sm font-semibold">{t("palette.title")}</h2>
      <p className="text-muted-foreground mt-1 mb-4 text-xs">{t("palette.dragHint")}</p>

      <div className="space-y-2">
        {NODE_TYPE_CONFIGS.map((config) => (
          <div
            key={config.type}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("application/reactflow", config.type);
              e.dataTransfer.effectAllowed = "move";
            }}
            className="hover:bg-accent flex cursor-grab items-center gap-3 rounded-lg border p-3 transition-colors active:cursor-grabbing"
          >
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
              style={{ backgroundColor: config.color + "20" }}
            >
              <config.icon className="h-4 w-4" style={{ color: config.color }} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium">{t(config.labelKey as never)}</p>
              <p className="text-muted-foreground truncate text-xs">
                {t(config.descriptionKey as never)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
