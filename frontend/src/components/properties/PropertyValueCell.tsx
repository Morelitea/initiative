import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Check, ExternalLink, Minus } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";
import {
  PropertyType,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

import { isEmptyPropertyValue } from "./propertyHelpers";
import { iconForPropertyType } from "./propertyTypeIcons";

type CellVariant = "cell" | "chip";

export interface PropertyValueCellProps {
  summary: PropertySummary | undefined;
  variant?: CellVariant;
  className?: string;
}

const formatNumber = (raw: unknown): string => {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return new Intl.NumberFormat().format(raw);
  }
  if (typeof raw === "string" && raw.trim() !== "") {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return new Intl.NumberFormat().format(parsed);
  }
  return "";
};

const formatDate = (raw: unknown, withTime: boolean): string => {
  if (typeof raw !== "string" || !raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date);
};

const coerceOptionMap = (options: PropertyOption[] | null | undefined) => {
  const map = new Map<string, PropertyOption>();
  for (const option of options ?? []) {
    map.set(option.value, option);
  }
  return map;
};

interface SelectChipProps {
  option: PropertyOption | undefined;
  slug: string;
  unknownLabel: string;
  dense?: boolean;
}

const SelectChip = ({ option, slug, unknownLabel, dense }: SelectChipProps) => {
  const label = option?.label ?? unknownLabel;
  const color = option?.color ?? null;
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 truncate",
        dense ? "text-xs" : "text-sm",
        !option && "italic"
      )}
      title={option ? option.label : slug}
    >
      {color ? (
        <span
          className="inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
      ) : null}
      <span className="truncate">{label}</span>
    </span>
  );
};

interface UserValue {
  id: number;
  full_name?: string | null;
  avatar_url?: string | null;
  avatar_base64?: string | null;
}

const extractUser = (raw: unknown): UserValue | null => {
  if (raw && typeof raw === "object" && "id" in raw) {
    const id = (raw as { id: unknown }).id;
    if (typeof id === "number" && Number.isFinite(id)) {
      return raw as UserValue;
    }
  }
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return { id: raw };
  }
  return null;
};

/**
 * Render a single PropertySummary value in either a `cell` (table) or
 * `chip` (card) layout. Empty values render an em-dash in `cell` mode and
 * return `null` in `chip` mode so cards aren't littered with unset rows.
 */
export const PropertyValueCell = ({
  summary,
  variant = "cell",
  className,
}: PropertyValueCellProps) => {
  const { t } = useTranslation("properties");
  const options = useMemo(() => coerceOptionMap(summary?.options), [summary?.options]);

  if (!summary || isEmptyPropertyValue(summary.value)) {
    if (variant === "chip") return null;
    return (
      <span className={cn("text-muted-foreground", className)} aria-label={t("cell.none")}>
        {t("cell.emptyValue")}
      </span>
    );
  }

  const { type, value } = summary;

  let body: React.ReactNode = null;

  switch (type) {
    case PropertyType.text: {
      body = <span className="truncate">{String(value ?? "")}</span>;
      break;
    }
    case PropertyType.url: {
      const href = typeof value === "string" ? value : "";
      body = (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary inline-flex max-w-full items-center gap-1 truncate hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="truncate">{href}</span>
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
        </a>
      );
      break;
    }
    case PropertyType.number: {
      body = <span className="tabular-nums">{formatNumber(value)}</span>;
      break;
    }
    case PropertyType.checkbox: {
      body =
        value === true ? (
          <Check className="h-4 w-4" aria-hidden />
        ) : (
          <Minus className="text-muted-foreground h-4 w-4" aria-hidden />
        );
      break;
    }
    case PropertyType.date: {
      body = <span>{formatDate(value, false)}</span>;
      break;
    }
    case PropertyType.datetime: {
      body = <span>{formatDate(value, true)}</span>;
      break;
    }
    case PropertyType.select: {
      const slug = String(value ?? "");
      const option = options.get(slug);
      body = (
        <SelectChip
          option={option}
          slug={slug}
          unknownLabel={t("input.unknownOption", { value: slug })}
          dense={variant === "chip"}
        />
      );
      break;
    }
    case PropertyType.multi_select: {
      const slugs = Array.isArray(value)
        ? (value as unknown[]).filter((v): v is string => typeof v === "string")
        : [];
      body = (
        <span className="flex max-w-full flex-wrap items-center gap-1">
          {slugs.map((slug) => (
            <SelectChip
              key={slug}
              option={options.get(slug)}
              slug={slug}
              unknownLabel={t("input.unknownOption", { value: slug })}
              dense
            />
          ))}
        </span>
      );
      break;
    }
    case PropertyType.user_reference: {
      const user = extractUser(value);
      if (!user) {
        body = <span className="text-muted-foreground italic">{t("cell.emptyValue")}</span>;
      } else {
        const name = user.full_name ?? `#${user.id}`;
        const userAvatarSrc = resolveUploadUrl(user.avatar_url) || user.avatar_base64 || undefined;
        body = (
          <span className="inline-flex max-w-full items-center gap-2 truncate">
            <Avatar className="h-5 w-5 text-[10px]">
              {userAvatarSrc ? <AvatarImage src={userAvatarSrc} alt={name} /> : null}
              <AvatarFallback userId={user.id}>{getInitials(user.full_name)}</AvatarFallback>
            </Avatar>
            <span className="truncate">{name}</span>
          </span>
        );
      }
      break;
    }
    default:
      body = null;
  }

  if (variant === "chip") {
    const Icon = iconForPropertyType(type);
    return (
      <span
        className={cn(
          "bg-muted text-muted-foreground inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-xs",
          className
        )}
      >
        <Icon className="h-3 w-3 shrink-0" aria-hidden />
        <span className="truncate font-medium">{summary.name}:</span>
        <span className="text-foreground max-w-[14rem] truncate">{body}</span>
      </span>
    );
  }

  return (
    <div className={cn("flex max-w-full min-w-0 items-center gap-1 truncate", className)}>
      {body}
    </div>
  );
};
