import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { OwnedDecoration } from "@/api/generated/initiativeAPI.schemas";
import { type Decoration, type DecorationKind, resolveDecoration } from "@/lib/profileDecorations";
import { cn } from "@/lib/utils";

/**
 * The decorations of one slot that this reader owns *and* this build can draw.
 *
 * Two filters, and the second one matters: a library is the server's answer and
 * may name a decoration from a pack whose artwork this build has never seen.
 * Offering a tile that renders as nothing would be worse than leaving it out.
 */
const wearable = (owned: OwnedDecoration[] | undefined, kind: DecorationKind): Decoration[] =>
  (owned ?? [])
    .filter((item) => item.kind === kind)
    .map((item) => resolveDecoration(item.id, kind))
    .filter((decoration): decoration is Decoration => Boolean(decoration));

/** One tile: the artwork, drawn the way its slot is worn. */
const Swatch = ({ decoration }: { decoration: Decoration }) => {
  if (decoration.kind === "banner") {
    return (
      <span
        className="block h-10 w-full rounded-sm bg-center bg-cover"
        style={{ backgroundImage: `url(${decoration.src})` }}
      />
    );
  }
  return (
    <span className="flex h-10 items-center justify-center">
      <img
        src={decoration.src}
        alt=""
        aria-hidden="true"
        className={decoration.kind === "frame" ? "size-10" : "size-7"}
      />
    </span>
  );
};

interface TileProps {
  label: string;
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  /** `radio` for a slot that holds one thing, `checkbox` for the badge row. */
  role: "radio" | "checkbox";
}

const Tile = ({ label, selected, onClick, children, role }: TileProps) => (
  <button
    type="button"
    role={role}
    aria-checked={selected}
    aria-label={label}
    title={label}
    onClick={onClick}
    className={cn(
      "relative rounded-md border-2 p-1.5 transition-colors",
      selected
        ? "border-primary bg-primary/5"
        : "border-transparent hover:border-muted-foreground/30"
    )}
  >
    {children}
    {selected ? (
      <Check className="absolute top-0.5 right-0.5 size-3.5 text-primary" aria-hidden="true" />
    ) : null}
  </button>
);

interface SlotPickerProps {
  kind: Extract<DecorationKind, "banner" | "frame">;
  value: string | null;
  onChange: (id: string | null) => void;
  owned: OwnedDecoration[] | undefined;
}

/**
 * The picker for a slot that holds one thing — the banner, the frame.
 *
 * Picking the tile that is already on takes it off, so "none" needs no tile of
 * its own and there is one way to end up bare.
 */
export const SlotPicker = ({ kind, value, onChange, owned }: SlotPickerProps) => {
  const { t } = useTranslation("profiles");
  const choices = wearable(owned, kind);

  if (choices.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("decorationPicker.empty")}</p>;
  }

  return (
    <div
      role="radiogroup"
      aria-label={t(`decorationPicker.${kind}`)}
      className="flex flex-wrap gap-2"
    >
      {choices.map((decoration) => (
        <Tile
          key={decoration.id}
          role="radio"
          label={t(decoration.labelKey)}
          selected={value === decoration.id}
          onClick={() => onChange(value === decoration.id ? null : decoration.id)}
        >
          <span className={kind === "banner" ? "block w-32" : "block w-12"}>
            <Swatch decoration={decoration} />
          </span>
        </Tile>
      ))}
    </div>
  );
};

interface BadgePickerProps {
  value: string[];
  onChange: (ids: string[]) => void;
  owned: OwnedDecoration[] | undefined;
  /** Mirrors ``MAX_PROFILE_BADGES`` on the server. */
  max: number;
}

/**
 * The picker for the badge row, which holds several.
 *
 * Order is the order they were picked, which is the order they are worn. Past
 * the cap the unpicked tiles stop responding rather than silently dropping the
 * oldest — what is worn is the reader's choice, not the picker's.
 */
export const BadgePicker = ({ value, onChange, owned, max }: BadgePickerProps) => {
  const { t } = useTranslation("profiles");
  const choices = wearable(owned, "badge");

  if (choices.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("decorationPicker.empty")}</p>;
  }

  const toggle = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter((worn) => worn !== id));
    } else if (value.length < max) {
      onChange([...value, id]);
    }
  };

  return (
    <div className="space-y-2">
      <div aria-label={t("decorationPicker.badge")} className="flex flex-wrap gap-2">
        {choices.map((decoration) => {
          const selected = value.includes(decoration.id);
          return (
            <Tile
              key={decoration.id}
              role="checkbox"
              label={t(decoration.labelKey)}
              selected={selected}
              onClick={() => toggle(decoration.id)}
            >
              <span className="block w-10">
                <Swatch decoration={decoration} />
              </span>
            </Tile>
          );
        })}
      </div>
      <p className="text-muted-foreground text-xs">
        {t("decorationPicker.badgeCount", { count: value.length, max })}
      </p>
    </div>
  );
};
