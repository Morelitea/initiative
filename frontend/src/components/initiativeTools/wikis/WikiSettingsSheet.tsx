import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Tool,
  WikiPageOrder,
  type WikiPageSummary,
  type WikiRead,
  WikiReadingWidth,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useUpdateWiki } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { toolSettingsRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** What the picker opens on when the wiki has no accent of its own. */
const DEFAULT_ACCENT = "#6366F1";

/** How many heading levels the contents list may show. */
const DEPTHS = [2, 3, 4] as const;

/** A labelled row: the control on the right, what it does underneath. */
const Setting = ({
  label,
  hint,
  control,
  className,
}: {
  label: string;
  hint?: string;
  control: React.ReactNode;
  className?: string;
}) => (
  <div className={cn("flex items-start justify-between gap-4 py-3", className)}>
    <div className="min-w-0 space-y-0.5">
      <p className="font-medium text-sm">{label}</p>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
    <div className="shrink-0">{control}</div>
  </div>
);

interface WikiSettingsSheetProps {
  wiki: WikiRead;
  pages: WikiPageSummary[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * What this wiki is for.
 *
 * A handbook is read front to back and ordered by hand; a world bible has two
 * hundred entries nobody orders by hand; a runbook is full of screenshots and
 * wants the whole screen. These are the choices that let one tool be all
 * three, so they sit together rather than being scattered over the surface.
 *
 * Each change saves on its own — there is no form to submit, because there is
 * no combination of these that has to be applied at once.
 */
export const WikiSettingsSheet = ({ wiki, pages, open, onOpenChange }: WikiSettingsSheetProps) => {
  const { t } = useTranslation("wikis");
  const gp = useGuildPath();
  const update = useUpdateWiki(wiki.id);

  const save = (patch: Parameters<typeof update.mutate>[0]) => update.mutate(patch);

  const orders = [
    {
      value: WikiPageOrder.manual,
      label: t("settings.orderManual"),
      hint: t("settings.orderManualHint"),
    },
    {
      value: WikiPageOrder.title,
      label: t("settings.orderTitle"),
      hint: t("settings.orderTitleHint"),
    },
    {
      value: WikiPageOrder.recently_updated,
      label: t("settings.orderRecent"),
      hint: t("settings.orderRecentHint"),
    },
  ];

  const widths = [
    {
      value: WikiReadingWidth.wide,
      label: t("settings.widthWide"),
      hint: t("settings.widthWideHint"),
    },
    {
      value: WikiReadingWidth.comfortable,
      label: t("settings.widthComfortable"),
      hint: t("settings.widthComfortableHint"),
    },
  ];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b px-5 py-4">
          <SheetTitle>{t("settings.title")}</SheetTitle>
          <SheetDescription>{t("settings.description")}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-2">
          <fieldset className="py-3">
            <legend className="font-medium text-sm">{t("settings.order")}</legend>
            <p className="pb-2 text-muted-foreground text-xs">{t("settings.orderDescription")}</p>
            <RadioGroup
              value={wiki.page_order}
              onValueChange={(value) => save({ page_order: value as WikiPageOrder })}
              className="gap-2"
            >
              {orders.map((option) => (
                <div key={option.value} className="flex items-start gap-2.5">
                  <RadioGroupItem
                    value={option.value}
                    id={`wiki-order-${option.value}`}
                    className="mt-0.5"
                  />
                  <Label htmlFor={`wiki-order-${option.value}`} className="space-y-0.5">
                    <span className="font-normal text-sm">{option.label}</span>
                    <span className="block text-muted-foreground text-xs">{option.hint}</span>
                  </Label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>

          <Separator />

          <Setting
            label={t("settings.counts")}
            hint={t("settings.countsHint")}
            control={
              <Switch
                checked={wiki.show_page_counts}
                onCheckedChange={(checked) => save({ show_page_counts: checked })}
                aria-label={t("settings.counts")}
              />
            }
          />

          <Separator />

          <Setting
            label={t("settings.contents")}
            hint={t("settings.contentsDescription")}
            control={
              <Select
                value={String(wiki.contents_depth)}
                onValueChange={(value) => save({ contents_depth: Number(value) })}
              >
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEPTHS.map((depth) => (
                    <SelectItem key={depth} value={String(depth)}>
                      {t("settings.contentsLevels", { count: depth })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />

          <Separator />

          <Setting
            label={t("settings.connections")}
            hint={t("settings.connectionsHint")}
            control={
              <Switch
                checked={wiki.show_connections}
                onCheckedChange={(checked) => save({ show_connections: checked })}
                aria-label={t("settings.connections")}
              />
            }
          />

          <Separator />

          <fieldset className="py-3">
            <legend className="font-medium text-sm">{t("settings.width")}</legend>
            <RadioGroup
              value={wiki.reading_width}
              onValueChange={(value) => save({ reading_width: value as WikiReadingWidth })}
              className="gap-2 pt-2"
            >
              {widths.map((option) => (
                <div key={option.value} className="flex items-start gap-2.5">
                  <RadioGroupItem
                    value={option.value}
                    id={`wiki-width-${option.value}`}
                    className="mt-0.5"
                  />
                  <Label htmlFor={`wiki-width-${option.value}`} className="space-y-0.5">
                    <span className="font-normal text-sm">{option.label}</span>
                    <span className="block text-muted-foreground text-xs">{option.hint}</span>
                  </Label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>

          <Separator />

          <Setting
            label={t("settings.accent")}
            hint={t("settings.accentHint")}
            className="items-center"
            control={
              <div className="flex items-center gap-2">
                <ColorPickerPopover
                  value={wiki.accent_color ?? DEFAULT_ACCENT}
                  onChangeComplete={(colour) => save({ accent_color: colour })}
                  triggerLabel={t("settings.accent")}
                />
                {wiki.accent_color ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8"
                    onClick={() => save({ accent_color: null })}
                  >
                    {t("settings.accentNone")}
                  </Button>
                ) : null}
              </div>
            }
          />

          <Separator />

          <Setting
            label={t("settings.template")}
            hint={t("settings.templateDescription")}
            control={
              <Select
                value={wiki.template_page_id ? String(wiki.template_page_id) : "none"}
                onValueChange={(value) =>
                  save({ template_page_id: value === "none" ? null : Number(value) })
                }
              >
                <SelectTrigger className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("settings.templateNone")}</SelectItem>
                  {pages.map((page) => (
                    <SelectItem key={page.id} value={String(page.id)}>
                      {page.title || t("pages.untitled")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />
        </div>

        <div className="border-t px-5 py-3">
          <Link
            to={gp(toolSettingsRoute(Tool.wiki, wiki.initiative_id, wiki.id))}
            className="flex items-center gap-1.5 text-muted-foreground text-sm hover:text-foreground"
          >
            {t("settings.more")}
            <ExternalLink className="size-3.5" aria-hidden />
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
};
