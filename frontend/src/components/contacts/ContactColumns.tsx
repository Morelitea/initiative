import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The row's own columns: picture, handle, name, and the communities in common.
 *
 * One template, used by the heading and by every row in every section, so the
 * page reads down as a table rather than as a stack of separate lists — the
 * same person under two communities lands on the same vertical lines.
 *
 * Every track is fixed or fractional. Sizing the last one to its contents
 * would make it as wide as whichever row holds the most icons, which differs
 * per section, and the columns would drift apart between them.
 */
export const CONTACT_ROW_GRID = cn(
  "grid grid-cols-[2rem_minmax(0,1fr)_5rem] items-center gap-x-3",
  "sm:grid-cols-[2rem_minmax(0,1.1fr)_minmax(0,1fr)_5rem]"
);

/** The row itself: everything above, plus the two controls that sit outside
 *  the link — the star, and the menu of what can be done about this person. */
export const CONTACT_ROW_OUTER = "grid grid-cols-[minmax(0,1fr)_2rem_2rem] items-center gap-1";

/**
 * The one heading over the whole page.
 *
 * It sits above the first section rather than repeating inside each, because
 * the columns are shared — naming them once is what says they are the same
 * columns all the way down.
 */
export const ContactColumnHeader = () => {
  const { t } = useTranslation("contacts");

  return (
    <div className={cn(CONTACT_ROW_OUTER, "border-b px-2 pb-2")}>
      <div className={CONTACT_ROW_GRID}>
        <span aria-hidden="true" />
        <span className="min-w-0 truncate text-muted-foreground text-xs">
          {t("columns.person")}
        </span>
        <span className="hidden min-w-0 truncate text-muted-foreground text-xs sm:block">
          {t("columns.name")}
        </span>
        <span className="text-muted-foreground text-xs">{t("columns.alsoIn")}</span>
      </div>
      <span aria-hidden="true" />
      <span aria-hidden="true" />
    </div>
  );
};

/**
 * Rows that are on their way.
 *
 * Drawn on the same template as real ones, so a page that is loading has the
 * shape and height of the page that replaces it and nothing jumps when it
 * lands.
 */
export const ContactRowsSkeleton = ({ count }: { count: number }) => (
  <ul className="space-y-0.5" aria-hidden="true">
    {Array.from({ length: count }, (_, index) => (
      // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
      <li key={index} className={cn(CONTACT_ROW_OUTER, "px-2")}>
        <div className={cn(CONTACT_ROW_GRID, "py-1.5")}>
          <Skeleton className="size-8 rounded-full" />
          <Skeleton className="h-3.5 w-32 max-w-full" />
          <Skeleton className="hidden h-3.5 w-24 max-w-full sm:block" />
          <span />
        </div>
        <span />
      </li>
    ))}
  </ul>
);
