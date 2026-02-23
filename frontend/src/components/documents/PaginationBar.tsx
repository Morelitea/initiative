import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export interface PaginationBarProps {
  page: number;
  pageSize: number;
  totalCount: number;
  hasNext: boolean;
  onPageChange: (updater: number | ((prev: number) => number)) => void;
  onPageSizeChange: (size: number) => void;
  onPrefetchPage: (page: number) => void;
}

export const PaginationBar = ({
  page,
  pageSize,
  totalCount,
  hasNext,
  onPageChange,
  onPageSizeChange,
  onPrefetchPage,
}: PaginationBarProps) => {
  const { t } = useTranslation("documents");
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground text-sm">{t("page.perPage")}</span>
        <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
          <SelectTrigger className="h-8 w-20">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            {PAGE_SIZE_OPTIONS.map((opt) => (
              <SelectItem key={opt} value={String(opt)}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-muted-foreground text-sm">
          {t("page.rangeOf", { start, end, total: totalCount })}
        </span>
      </div>
      <div className="flex items-center gap-2 self-end sm:self-auto">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          onMouseEnter={() => onPrefetchPage(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
          {t("page.previous")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange((p) => p + 1)}
          disabled={!hasNext}
          onMouseEnter={() => hasNext && onPrefetchPage(page + 1)}
        >
          {t("page.next")}
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};
