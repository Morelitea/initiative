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
  onToggle: () => void;
  children: React.ReactNode;
  /** `radio` for a slot that holds one thing, `checkbox` for the badge row. */
  control: "radio" | "checkbox";
  /** Groups the radios of one slot, so the browser treats them as alternatives. */
  name?: string;
  /** A tile past the cap, which stays visible and stops responding. */
  disabled?: boolean;
}

/** A checked input needs a change handler; this one is driven by its click. */
const NO_CHANGE = () => {};

/**
 * One decoration, as something to turn on.
 *
 * A real input rather than a button wearing a role: it arrives with the state,
 * the keyboard and the grouping already correct, and the artwork is the label.
 * The input is hidden from sight, not from the page.
 */
const Tile = ({ label, selected, onToggle, children, control, name, disabled }: TileProps) => (
  <label
    title={label}
    className={cn(
      "relative block rounded-md border-2 p-1.5 transition-colors",
      disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
      selected
        ? "border-primary bg-primary/5"
        : "border-transparent hover:border-muted-foreground/30",
      "focus-within:ring-2 focus-within:ring-ring"
    )}
  >
    <input
      type={control}
      name={name}
      checked={selected}
      disabled={disabled}
      // The click, not the change: picking the one already on takes it off, and
      // a radio reports no change when it is clicked while checked.
      onClick={onToggle}
      onChange={NO_CHANGE}
      aria-label={label}
      className="sr-only"
    />
    {children}
    {selected ? (
      <Check className="absolute top-0.5 right-0.5 size-3.5 text-primary" aria-hidden="true" />
    ) : null}
  </label>
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
    <fieldset className="flex min-w-0 flex-wrap gap-2">
      <legend className="sr-only">{t(`decorationPicker.${kind}`)}</legend>
      {choices.map((decoration) => (
        <Tile
          key={decoration.id}
          control="radio"
          name={`decoration-${kind}`}
          label={t(decoration.labelKey)}
          selected={value === decoration.id}
          onToggle={() => onChange(value === decoration.id ? null : decoration.id)}
        >
          <span className={kind === "banner" ? "block w-32" : "block w-12"}>
            <Swatch decoration={decoration} />
          </span>
        </Tile>
      ))}
    </fieldset>
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
      <fieldset className="flex min-w-0 flex-wrap gap-2">
        <legend className="sr-only">{t("decorationPicker.badge")}</legend>
        {choices.map((decoration) => {
          const selected = value.includes(decoration.id);
          return (
            <Tile
              key={decoration.id}
              control="checkbox"
              label={t(decoration.labelKey)}
              selected={selected}
              disabled={!selected && value.length >= max}
              onToggle={() => toggle(decoration.id)}
            >
              <span className="block w-10">
                <Swatch decoration={decoration} />
              </span>
            </Tile>
          );
        })}
      </fieldset>
      <p className="text-muted-foreground text-xs">
        {t("decorationPicker.badgeCount", { count: value.length, max })}
      </p>
    </div>
  );
};
