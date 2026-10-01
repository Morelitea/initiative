import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { GuildCategory } from "@/api/generated/initiativeAPI.schemas";
import { ContinueButton, SkipButton } from "@/components/start/stepParts";
import { Button } from "@/components/ui/button";
import { GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";

/** Each shelf's own colour, spread evenly around the wheel. */
const shelfColour = (index: number): string =>
  `oklch(0.7 0.16 ${Math.round((index * 360) / GUILD_CATEGORIES.length)})`;

/** The directory shelves to open on, as many as they like. */
export const InterestStep = ({
  value,
  onChange,
  onContinue,
  onSkip,
  disabled,
}: {
  value: GuildCategory[];
  onChange: (categories: GuildCategory[]) => void;
  onContinue: () => void;
  onSkip: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation(["guilds", "common"]);
  const toggle = (category: GuildCategory) =>
    onChange(
      value.includes(category)
        ? value.filter((picked) => picked !== category)
        : // Kept in the directory's own order, whatever order they were tapped in.
          GUILD_CATEGORIES.filter((item) => item === category || value.includes(item))
    );
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {GUILD_CATEGORIES.map((category, index) => {
          const picked = value.includes(category);
          return (
            <Button
              key={category}
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={picked}
              onClick={() => toggle(category)}
              className="rounded-full aria-pressed:border-primary aria-pressed:bg-primary/10"
            >
              {picked ? (
                <Check className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              ) : (
                <span
                  aria-hidden="true"
                  className="size-2.5 rotate-45 rounded-[2px]"
                  style={{ backgroundColor: shelfColour(index) }}
                />
              )}
              {guildCategoryLabel(category, t)}
            </Button>
          );
        })}
      </div>
      <ContinueButton onClick={onContinue} disabled={disabled} />
      <SkipButton onClick={onSkip} disabled={disabled} />
    </>
  );
};
