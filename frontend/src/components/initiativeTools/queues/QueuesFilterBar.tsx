import { useTranslation } from "react-i18next";
import { Filter, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

const INITIATIVE_FILTER_ALL = "all";

export type StatusFilter = "all" | "active" | "inactive";

type QueuesFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (value: StatusFilter) => void;
  initiativeFilter: string;
  onInitiativeFilterChange: (value: string) => void;
  lockedInitiativeId: number | null;
  lockedInitiativeName: string | null;
  initiatives: InitiativeRead[];
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
};

export const QueuesFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  statusFilter,
  onStatusFilterChange,
  initiativeFilter,
  onInitiativeFilterChange,
  lockedInitiativeId,
  lockedInitiativeName,
  initiatives,
  filtersOpen,
  onFiltersOpenChange,
}: QueuesFilterBarProps) => {
  const { t } = useTranslation(["queues", "common"]);

  return (
    <Collapsible open={filtersOpen} onOpenChange={onFiltersOpenChange} className="space-y-2">
      <div className="flex items-center justify-between sm:hidden">
        <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
          <Filter className="h-4 w-4" />
          {t("filters.heading")}
        </div>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-3">
            {filtersOpen ? t("filters.hide") : t("filters.show")}
            <ChevronDown
              className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent forceMount className="data-[state=closed]:hidden">
        <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
          <div className="w-full space-y-2 lg:flex-1">
            <Label
              htmlFor="queue-search"
              className="text-muted-foreground block text-xs font-medium"
            >
              {t("filters.filterByName")}
            </Label>
            <Input
              id="queue-search"
              placeholder={t("filters.searchQueues")}
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
              className="min-w-60"
            />
          </div>
          <div className="w-full space-y-2 sm:w-48">
            <Label
              htmlFor="queue-status-filter"
              className="text-muted-foreground block text-xs font-medium"
            >
              {t("filters.status")}
            </Label>
            <Select
              value={statusFilter}
              onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}
            >
              <SelectTrigger id="queue-status-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("filters.allStatuses")}</SelectItem>
                <SelectItem value="active">{t("filters.activeOnly")}</SelectItem>
                <SelectItem value="inactive">{t("filters.inactiveOnly")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {lockedInitiativeId ? (
            <div className="w-full space-y-2 sm:w-60">
              <Label className="text-muted-foreground block text-xs font-medium">
                {t("filters.filterByInitiative")}
              </Label>
              <p className="text-sm font-medium">
                {lockedInitiativeName ?? t("filters.allInitiatives")}
              </p>
            </div>
          ) : (
            initiatives.length > 1 && (
              <div className="w-full space-y-2 sm:w-60">
                <Label
                  htmlFor="queue-initiative-filter"
                  className="text-muted-foreground block text-xs font-medium"
                >
                  {t("filters.filterByInitiative")}
                </Label>
                <Select value={initiativeFilter} onValueChange={onInitiativeFilterChange}>
                  <SelectTrigger id="queue-initiative-filter">
                    <SelectValue placeholder={t("filters.allInitiatives")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={INITIATIVE_FILTER_ALL}>
                      {t("filters.allInitiatives")}
                    </SelectItem>
                    {initiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
