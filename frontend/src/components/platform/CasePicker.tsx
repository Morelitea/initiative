/**
 * Chooses the operations case an access grant is for.
 *
 * The list is the open cases the reader can open, at most a few dozen, so it
 * arrives whole and is searched here. Each reads as its number and title, with
 * the stream it came in on beside it and a mark on the ones assigned to the
 * reader, which the server lists first.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GrantCaseRead } from "@/api/generated/initiativeAPI.schemas";
import { AsyncCombobox } from "@/components/ui/async-combobox";

/** The value the "no case" row is chosen by, where a case is optional. */
const NO_CASE = "none";

/** How a case reads in the list and on the closed picker. */
export const caseLabel = (item: Pick<GrantCaseRead, "task_id" | "title">): string =>
  `#${item.task_id} · ${item.title}`;

export const CasePicker = ({
  cases,
  value,
  onChange,
  optional = false,
  loading = false,
  disabled = false,
  "aria-label": ariaLabel,
  className,
}: {
  cases: GrantCaseRead[];
  /** The chosen case's task id. It may name a case the list no longer holds. */
  value: number | null;
  onChange: (taskId: number | null) => void;
  /** Offer a row for choosing no case at all. */
  optional?: boolean;
  loading?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}) => {
  const { t } = useTranslation(["settings", "intake"]);
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const shown = needle
    ? cases.filter((item) => caseLabel(item).toLowerCase().includes(needle))
    : cases;
  const chosen = value == null ? undefined : cases.find((item) => item.task_id === value);

  return (
    <AsyncCombobox
      className={className}
      aria-label={ariaLabel}
      value={value == null ? null : String(value)}
      selectedLabel={value == null ? null : chosen ? caseLabel(chosen) : `#${value}`}
      items={[
        ...(optional && !needle ? [{ value: NO_CASE, label: t("accessGrants.caseNone") }] : []),
        ...shown.map((item) => ({
          value: String(item.task_id),
          label: caseLabel(item),
          hint: item.mine
            ? `${t(`intake:streams.${item.stream}.title`)} · ${t("accessGrants.caseYours")}`
            : t(`intake:streams.${item.stream}.title`),
        })),
      ]}
      onSearchChange={setSearch}
      // Searched here, so there is nothing to wait for.
      debounceMs={0}
      loading={loading}
      placeholder={t("accessGrants.casePlaceholder")}
      searchPlaceholder={t("accessGrants.caseSearch")}
      emptyMessage={t("accessGrants.caseEmpty")}
      disabled={disabled}
      onValueChange={(next) => onChange(next === NO_CASE ? null : Number(next))}
    />
  );
};
