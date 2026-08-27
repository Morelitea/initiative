/**
 * The gate between a private guild and a listed one.
 *
 * Listing publishes a guild to everyone signed in, so it is a decision made
 * once, deliberately, with both of its conditions in front of you: at least one
 * category, and a certification about what the guild contains. Neither is a
 * default anyone can click past — Confirm stays disabled until both are met,
 * and the server refuses the same two conditions independently.
 *
 * The certification is what answers the guild's 18+ question. Ticking it here
 * is the only path from unanswered to "no", which is why the statement sits
 * with the checkbox rather than in a policy page nobody opens.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildCategory } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";
import { cn } from "@/lib/utils";

/** One key per line of the certification, so a translator sees each claim on
 *  its own rather than one paragraph to keep in sync. */
const CERTIFY_KEYS = [
  "certifyPorn",
  "certifyMinors",
  "certifyIllegal",
  "certifyViolence",
  "certifyHate",
] as const;

export const PublishGuildDialog = ({
  open,
  saving,
  initialCategories,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  saving: boolean;
  initialCategories: GuildCategory[];
  onCancel: () => void;
  onConfirm: (categories: GuildCategory[]) => void | Promise<void>;
}) => {
  const { t } = useTranslation(["guilds", "common"]);
  const [categories, setCategories] = useState<GuildCategory[]>(initialCategories);
  const [certified, setCertified] = useState(false);

  // Every opening starts from the guild's current shelves and an un-ticked
  // certification: it is an assertion made now, not one a previous visit made.
  useEffect(() => {
    if (open) {
      setCategories(initialCategories);
      setCertified(false);
    }
  }, [open, initialCategories]);

  const toggleCategory = (category: GuildCategory) => {
    setCategories((current) =>
      current.includes(category)
        ? current.filter((value) => value !== category)
        : [...current, category]
    );
  };

  const ready = categories.length > 0 && certified;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !saving && onCancel()}>
      <DialogContent className="max-h-screen overflow-y-auto bg-card sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("guilds:community.publish.title")}</DialogTitle>
          <DialogDescription>{t("guilds:community.publish.description")}</DialogDescription>
        </DialogHeader>

        <fieldset className="space-y-2">
          <legend className="font-medium text-sm">
            {t("guilds:community.publish.categoriesLabel")}
          </legend>
          <p className="text-muted-foreground text-sm">
            {t("guilds:community.publish.categoriesHint")}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            {GUILD_CATEGORIES.map((category) => {
              const selected = categories.includes(category);
              return (
                <button
                  key={category}
                  type="button"
                  onClick={() => toggleCategory(category)}
                  aria-pressed={selected}
                  className={cn(
                    "rounded-full border px-3 py-1 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-input text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  {guildCategoryLabel(category, t)}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="space-y-3 rounded-lg border bg-muted/40 p-3">
          <div className="flex items-start gap-3">
            <Checkbox
              id="guild-certify-no-adult-content"
              checked={certified}
              onCheckedChange={(next) => setCertified(next === true)}
              className="mt-0.5"
            />
            <Label
              htmlFor="guild-certify-no-adult-content"
              className="font-medium text-sm leading-snug"
            >
              {t("guilds:community.publish.certifyLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("guilds:community.publish.certifyIntro")}
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {CERTIFY_KEYS.map((key) => (
              <li key={key}>{t(`guilds:community.publish.${key}`)}</li>
            ))}
          </ul>
          <p className="font-medium text-sm">{t("guilds:community.publish.certifyDuty")}</p>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
            {t("common:cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => void onConfirm(categories)}
            disabled={!ready || saving}
          >
            {saving ? t("guilds:settings.saving") : t("guilds:community.publish.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
