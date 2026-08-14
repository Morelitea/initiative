/**
 * One placed widget: its data, its chrome, and its authoring affordances.
 *
 * Sits between the canvas (which owns position) and `WidgetTile` (which owns
 * running the widget and drawing its scene). Everything visible here is app
 * code — the drag handle, the menu, the unbound state — because a widget draws
 * only inside its box and must never be able to render something that looks
 * like the frame around it.
 */

import { GripVertical, MoreVertical, Settings2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { appWidgetSample, appWidgetSource } from "@/api/appData";
import { WidgetTile } from "@/components/initiativeTools/dashboards/WidgetTile";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppWidgetCatalog } from "@/hooks/useAppData";
import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { cn } from "@/lib/utils";
import { type DefinitionWidget, isAppWidgetType, unboundSlots } from "@/lib/widgets/definition";
import { SAMPLE_NOW, sampleFor } from "@/lib/widgets/sampleData";

export interface DashboardWidgetProps {
  widget: DefinitionWidget;
  binding: WidgetBinding;
  /** The dashboard's own initiative — the only one its widgets read from. */
  initiativeId: number | undefined;
  /** The dashboard row itself. Only the `app` source needs it: its data is
   *  guild-level, so the proxy is told which initiative-scoped surface is
   *  asking and decides against that row's gates. */
  dashboardId?: number;
  canEdit: boolean;
  /** Draw the sample library instead of resolving the binding — nothing is
   *  fetched at all. This is the marketplace preview's mode: a listing that
   *  isn't installed shows what it *looks like*, never anyone's data, so it
   *  renders the same for every viewer. */
  sampleData?: boolean;
  onConfigure?: (widgetId: string) => void;
  onRemove?: (widgetId: string) => void;
}

export function DashboardWidget({
  widget,
  binding,
  initiativeId,
  dashboardId,
  canEdit,
  sampleData,
  onConfigure,
  onRemove,
}: DashboardWidgetProps) {
  const { t } = useTranslation("dashboards");
  const isAppWidget = isAppWidgetType(widget.type);

  // An app widget's module lives in the install's pinned definition rather than
  // in this build's registry — the seam `WidgetTile.source` exists for. The
  // catalog is one shared query per guild, so a canvas full of app widgets
  // resolves them all from one request.
  //
  // In sample mode it is fetched too, and only then: a preview draws the app's
  // *own* sample rows through the app's own module, so what it shows is the
  // listing rather than a stand-in. It still issues no data request — no
  // initiative, no dashboard, nothing to fetch.
  const appCatalogQuery = useAppWidgetCatalog(isAppWidget);
  const moduleSource = isAppWidget ? appWidgetSource(appCatalogQuery.data, widget.type) : undefined;

  // Named from its own module, like every widget: an app names its widgets in
  // the manifest, so a marketplace tile has a real title without a locale edit
  // here. Falls back to the type id until the sandbox read resolves.
  const { name } = useWidgetMeta(widget.type, moduleSource);

  // In sample mode the hook still runs (hooks are unconditional) but is handed
  // no initiative, which fail-closes every query — a preview issues no
  // requests, exactly like the widget picker's.
  const live = useWidgetData(
    binding,
    sampleData ? undefined : initiativeId,
    sampleData ? undefined : dashboardId
  );

  const appSampleRows = appWidgetSample(appCatalogQuery.data, widget.type, binding.source_id);
  const data = sampleData
    ? isAppWidget
      ? { source: "app" as const, rows: appSampleRows }
      : sampleFor(binding.source, widget.type)
    : live.data;
  const isLoading = sampleData ? false : live.isLoading;
  const isUnbound = sampleData ? false : live.isUnbound;
  const errorCode = sampleData ? undefined : live.errorCode;

  const title = widget.title || name;
  const missing = unboundSlots(binding);

  return (
    <section
      className="flex h-full w-full flex-col overflow-hidden rounded-lg border bg-card text-card-foreground"
      aria-label={title}
    >
      <header
        className={cn(
          "flex shrink-0 items-center gap-1 border-b px-2 py-1.5",
          canEdit && "cursor-grab active:cursor-grabbing"
        )}
        // The whole header is the drag handle, so a widget's own content never
        // becomes one — RGL is told to grab only on this attribute.
        {...(canEdit ? { "data-widget-handle": true } : {})}
      >
        {canEdit && (
          <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <h3 className="min-w-0 flex-1 truncate font-semibold text-sm">{title}</h3>
        {canEdit && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 shrink-0"
                aria-label={t("canvas.widgetMenu", { widget: title })}
                // Stops a click on the menu from starting a drag.
                onPointerDown={(event) => event.stopPropagation()}
              >
                <MoreVertical className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onConfigure?.(widget.id)}>
                <Settings2 className="mr-2 h-4 w-4" />
                {t("canvas.configure")}
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive" onSelect={() => onRemove?.(widget.id)}>
                <Trash2 className="mr-2 h-4 w-4" />
                {t("canvas.remove")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </header>

      <div className="min-h-0 flex-1 p-2">
        {isUnbound && missing.length ? (
          <UnboundNotice canEdit={canEdit} onConfigure={() => onConfigure?.(widget.id)} />
        ) : (
          <WidgetTile
            type={widget.type}
            data={data}
            config={widget.options}
            source={moduleSource}
            errorCode={errorCode}
            isLoading={isLoading || (isAppWidget && appCatalogQuery.isLoading)}
            now={sampleData ? SAMPLE_NOW : undefined}
            chromeless
          />
        )}
      </div>
    </section>
  );
}

/** A widget whose binding still has empty slots — an installed listing before
 *  someone points it at this guild's counter. Not an error, a next step. */
function UnboundNotice({ canEdit, onConfigure }: { canEdit: boolean; onConfigure: () => void }) {
  const { t } = useTranslation("dashboards");
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
      <p className="text-muted-foreground text-sm">{t("canvas.unbound")}</p>
      {canEdit && (
        <Button size="sm" variant="outline" onClick={onConfigure}>
          {t("canvas.configure")}
        </Button>
      )}
    </div>
  );
}
