import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { WidgetErrorCode } from "@/lib/widgets/errors";

/** Why a widget, or one picture in it, could not be drawn. */
export function WidgetError({ code, detail }: { code: WidgetErrorCode; detail?: string }) {
  const { t } = useTranslation("dashboards");
  // Every failure has a localized line; the interpreter's own message is shown
  // underneath because a widget author debugging their module needs it, and it
  // is the only diagnostic that crosses the sandbox boundary.
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-1 p-2 text-center">
      <AlertTriangle className="h-4 w-4 text-muted-foreground" aria-hidden />
      <p className="text-muted-foreground text-sm">
        {t(`widgetError.${code}`, { defaultValue: t("widgetError.default") })}
      </p>
      {detail && (
        <p className="max-w-full truncate font-mono text-muted-foreground/70 text-xs">{detail}</p>
      )}
    </div>
  );
}
