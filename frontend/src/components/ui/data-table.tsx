"use client";

import {
  Fragment,
  memo,
  type ReactNode,
  useMemo,
  useRef,
  useState,
  useId,
  useEffect,
  useCallback,
} from "react";
import { useTranslation } from "react-i18next";
import {
  ColumnDef,
  Row,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
  type RowSelectionState,
  getPaginationRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getGroupedRowModel,
  getExpandedRowModel,
  type GroupingState,
  type TableState,
  type PaginationState,
  type Table as TableType,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, MoreVertical } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { commandFilter } from "@/lib/fuzzyMatch";

interface GroupingOption {
  id: string;
  label: string;
}

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  rowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  enableFilterInput?: boolean;
  filterInputPlaceholder?: string;
  filterInputColumnKey?: string;
  enableColumnVisibilityDropdown?: boolean;
  enablePagination?: boolean;
  enableResetSorting?: boolean;
  initialSorting?: SortingState;
  initialState?: Partial<TableState>;
  pageSizeOptions?: number[];
  groupingOptions?: GroupingOption[];
  helpText?: ReactNode | ((table: TableType<TData>) => ReactNode);
  enableRowSelection?: boolean;
  onRowSelectionChange?: (selectedRows: TData[]) => void;
  getRowId?: (row: TData) => string;
  onExitSelection?: () => void;
  manualPagination?: boolean;
  pageCount?: number;
  rowCount?: number;
  onPaginationChange?: (pagination: PaginationState) => void;
  onPrefetchPage?: (pageIndex: number) => void;
  manualSorting?: boolean;
  onSortingChange?: (sorting: SortingState) => void;
  onGroupingChange?: (grouping: GroupingState) => void;
  enableVirtualization?: boolean;
  virtualRowHeight?: number;
  virtualOverscan?: number;
  virtualContainerHeight?: string;
}

export interface DataTableRowWrapperProps<TData> {
  row: Row<TData>;
  children: ReactNode;
  /** When virtualization is enabled, apply these to the row element for positioning. */
  virtualStyle?: React.CSSProperties;
  /** When virtualization is enabled, set this as data-index on the row element. */
  virtualIndex?: number;
  /** When virtualization is enabled, attach this ref to the row element for measurement. */
  measureRef?: (el: HTMLElement | null) => void;
}

const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const GROUPING_NONE_VALUE = "__none__";

export function DataTable<TData, TValue>({
  columns,
  data,
  rowWrapper,
  enableFilterInput = false,
  filterInputPlaceholder = "Filter...",
  filterInputColumnKey = "name",
  enableColumnVisibilityDropdown = false,
  enablePagination = false,
  enableResetSorting: enableClearSorting = false,
  initialSorting,
  initialState,
  pageSizeOptions,
  groupingOptions,
  helpText,
  enableRowSelection = false,
  onRowSelectionChange,
  getRowId,
  onExitSelection,
  manualPagination = false,
  pageCount: externalPageCount,
  rowCount: externalRowCount,
  onPaginationChange: externalOnPaginationChange,
  onPrefetchPage,
  manualSorting = false,
  onSortingChange: externalOnSortingChange,
  onGroupingChange: externalOnGroupingChange,
  enableVirtualization = false,
  virtualRowHeight = 48,
  virtualOverscan = 5,
  virtualContainerHeight = "h-[60vh]",
}: DataTableProps<TData, TValue>) {
  const { t } = useTranslation("common");
  const initialStateRef = useRef<Partial<TableState> | undefined>(initialState);
  const initialSortingRef = useRef<SortingState>(initialSorting ? [...initialSorting] : []);
  const groupingEnabled = Boolean(groupingOptions && groupingOptions.length > 0);
  const initialGroupingRef = useRef<GroupingState>(
    groupingEnabled && Array.isArray(initialStateRef.current?.grouping)
      ? [...(initialStateRef.current?.grouping as GroupingState)]
      : []
  );
  const resolveInitialPagination = (): PaginationState => {
    const paginationState = initialStateRef.current?.pagination as PaginationState | undefined;
    return {
      pageIndex: paginationState?.pageIndex ?? 0,
      pageSize: paginationState?.pageSize ?? DEFAULT_PAGE_SIZE,
    };
  };
  const initialPaginationRef = useRef<PaginationState>(resolveInitialPagination());
  const [sorting, setSorting] = useState<SortingState>(() => initialSortingRef.current);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(
    () => (initialStateRef.current?.columnFilters as ColumnFiltersState) ?? []
  );
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    () => initialStateRef.current?.columnVisibility ?? {}
  );
  const [grouping, setGrouping] = useState<GroupingState>(() =>
    groupingEnabled ? initialGroupingRef.current : []
  );
  const [pagination, setPagination] = useState<PaginationState>(() => initialPaginationRef.current);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [selectionModeActive, setSelectionModeActive] = useState(false);
  const groupingSelectId = useId();
  const computedInitialState: Partial<TableState> = {
    sorting: initialSortingRef.current,
    ...(initialStateRef.current ?? {}),
  };
  if (groupingEnabled && computedInitialState.expanded === undefined) {
    computedInitialState.expanded = true;
  }
  if (enablePagination) {
    computedInitialState.pagination = initialPaginationRef.current;
  }
  const resolvedPageSizeOptions = useMemo(() => {
    const baseOptions =
      pageSizeOptions && pageSizeOptions.length > 0 ? pageSizeOptions : DEFAULT_PAGE_SIZE_OPTIONS;
    const sanitized = Array.from(
      new Set(baseOptions.filter((option) => Number.isFinite(option) && option > 0))
    );
    return sanitized.length > 0 ? sanitized : [DEFAULT_PAGE_SIZE];
  }, [pageSizeOptions]);

  const columnsWithSelection = useMemo(() => {
    if (!enableRowSelection || !selectionModeActive) {
      return columns;
    }

    const selectionColumn: ColumnDef<TData, TValue> = {
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() && "indeterminate")
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label={t("selectAll")}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label={t("selectRow")}
        />
      ),
      enableSorting: false,
      enableHiding: false,
    };

    return [selectionColumn, ...columns];
  }, [enableRowSelection, selectionModeActive, columns, t]);

  const handlePaginationChange = useMemo(() => {
    if (!enablePagination) return undefined;
    if (manualPagination && externalOnPaginationChange) {
      return (updater: PaginationState | ((old: PaginationState) => PaginationState)) => {
        const newState = typeof updater === "function" ? updater(pagination) : updater;
        setPagination(newState);
        externalOnPaginationChange(newState);
      };
    }
    return setPagination;
  }, [enablePagination, manualPagination, externalOnPaginationChange, pagination]);

  const handleSortingChange = useMemo(() => {
    if (externalOnSortingChange) {
      return (updater: SortingState | ((old: SortingState) => SortingState)) => {
        const newState = typeof updater === "function" ? updater(sorting) : updater;
        setSorting(newState);
        externalOnSortingChange(newState);
      };
    }
    return setSorting;
  }, [externalOnSortingChange, sorting]);

  const handleGroupingChange = useCallback(
    (updater: GroupingState | ((old: GroupingState) => GroupingState)) => {
      setGrouping((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        externalOnGroupingChange?.(next);
        return next;
      });
    },
    [externalOnGroupingChange]
  );

  const table = useReactTable({
    data,
    columns: columnsWithSelection,
    getCoreRowModel: getCoreRowModel(),
    defaultColumn: {
      filterFn: (row, columnId, filterValue: string) => {
        const cellValue = String(row.getValue(columnId) ?? "");
        return commandFilter(cellValue, filterValue) > 0;
      },
    },
    onSortingChange: handleSortingChange,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onGroupingChange: groupingEnabled ? handleGroupingChange : undefined,
    onPaginationChange: handlePaginationChange,
    onRowSelectionChange: enableRowSelection ? setRowSelection : undefined,
    enableRowSelection: enableRowSelection,
    getRowId: getRowId,
    getPaginationRowModel:
      enablePagination && !manualPagination ? getPaginationRowModel() : undefined,
    getSortedRowModel: manualSorting && !groupingEnabled ? undefined : getSortedRowModel(),
    manualSorting: manualSorting,
    getFilteredRowModel: getFilteredRowModel(),
    getGroupedRowModel: groupingEnabled ? getGroupedRowModel() : undefined,
    getExpandedRowModel: groupingEnabled ? getExpandedRowModel() : undefined,
    manualPagination: manualPagination,
    ...(manualPagination && externalPageCount !== undefined
      ? { pageCount: externalPageCount }
      : {}),
    ...(manualPagination && externalRowCount !== undefined ? { rowCount: externalRowCount } : {}),
    initialState: computedInitialState,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      ...(groupingEnabled ? { grouping } : {}),
      ...(enablePagination ? { pagination } : {}),
      ...(enableRowSelection ? { rowSelection } : {}),
    },
  });
  const pageSize = table.getState().pagination?.pageSize ?? DEFAULT_PAGE_SIZE;
  const pageSizeChoices = useMemo(() => {
    const options = resolvedPageSizeOptions.includes(pageSize)
      ? resolvedPageSizeOptions
      : [...resolvedPageSizeOptions, pageSize];
    return [...options].sort((a, b) => a - b);
  }, [resolvedPageSizeOptions, pageSize]);
  const normalizedGroupingOptions = useMemo<GroupingOption[]>(() => {
    if (!groupingOptions || groupingOptions.length === 0) {
      return [];
    }
    return groupingOptions.map((option) => ({ ...option }));
  }, [groupingOptions]);
  const groupingChoices = useMemo(() => {
    if (normalizedGroupingOptions.length === 0) {
      return grouping.length > 0 ? grouping.map((id) => ({ id, label: id })) : [];
    }
    const missing = grouping.filter(
      (id) => !normalizedGroupingOptions.some((option) => option.id === id)
    );
    if (missing.length === 0) {
      return normalizedGroupingOptions;
    }
    return [...normalizedGroupingOptions, ...missing.map((id) => ({ id, label: id }))];
  }, [normalizedGroupingOptions, grouping]);
  const hasGroupingOptions = groupingChoices.length > 0;
  const groupingColumnIdSet = useMemo(
    () => new Set(groupingChoices.map((option) => option.id)),
    [groupingChoices]
  );
  const groupingSelectValue = grouping.length > 0 ? grouping[0] : GROUPING_NONE_VALUE;
  useEffect(() => {
    if (!groupingEnabled && grouping.length > 0) {
      setGrouping([]);
    }
  }, [groupingEnabled, grouping, groupingColumnIdSet]);
  useEffect(() => {
    if (!groupingEnabled || grouping.length > 0) {
      return;
    }
    setSorting((previousSorting) => {
      const filtered = previousSorting.filter((sort) => !groupingColumnIdSet.has(sort.id));
      if (
        filtered.length === previousSorting.length ||
        filtered.every(
          (sort, index) =>
            sort.id === previousSorting[index].id && sort.desc === previousSorting[index].desc
        )
      ) {
        return previousSorting;
      }
      return filtered;
    });
  }, [groupingEnabled, grouping, groupingColumnIdSet]);
  useEffect(() => {
    if (!groupingEnabled || grouping.length === 0) {
      return;
    }
    setSorting((previousSorting) => {
      const groupingSet = new Set(grouping);
      const previousSortMap = new Map(previousSorting.map((sort) => [sort.id, sort]));
      let changed = false;
      const rest = previousSorting.filter((sort) => {
        if (groupingSet.has(sort.id)) {
          if (sort.desc) {
            changed = true;
          }
          return false;
        }
        if (groupingColumnIdSet.has(sort.id)) {
          changed = true;
          return false;
        }
        return true;
      });
      const groupingSorting = grouping.map((groupId, index) => {
        const existing = previousSortMap.get(groupId);
        if (!existing) {
          changed = true;
          return { id: groupId, desc: false };
        }
        if (existing.desc) {
          changed = true;
        }
        if (previousSorting.indexOf(existing) !== index) {
          changed = true;
        }
        return existing.desc ? { ...existing, desc: false } : existing;
      });
      const newSorting = [...groupingSorting, ...rest];
      if (
        !changed &&
        newSorting.length === previousSorting.length &&
        newSorting.every(
          (sort, idx) =>
            sort.id === previousSorting[idx].id && sort.desc === previousSorting[idx].desc
        )
      ) {
        return previousSorting;
      }
      return newSorting;
    });
  }, [groupingEnabled, grouping, groupingColumnIdSet]);

  useEffect(() => {
    if (enableRowSelection && selectionModeActive && onRowSelectionChange) {
      const selectedRows = table.getFilteredSelectedRowModel().rows.map((row) => row.original);
      onRowSelectionChange(selectedRows);
    }
  }, [rowSelection, enableRowSelection, selectionModeActive, onRowSelectionChange, table]);

  useEffect(() => {
    if (!selectionModeActive && Object.keys(rowSelection).length > 0) {
      setRowSelection({});
    }
  }, [selectionModeActive, rowSelection]);

  const handleExitSelection = useCallback(() => {
    setSelectionModeActive(false);
    setRowSelection({});
    if (onExitSelection) {
      onExitSelection();
    }
  }, [onExitSelection]);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => virtualRowHeight,
    overscan: virtualOverscan,
    enabled: enableVirtualization,
  });

  const visibleColCount = table.getVisibleLeafColumns().length || columns.length;

  // When virtualization is enabled, pagination is disabled (mutually exclusive)
  const showPagination = enablePagination && !enableVirtualization;

  // Stable key that changes when visible columns change (selection mode toggle, column dropdown).
  // Used by MemoizedVirtualCells to know when to re-render.
  const visibleColumnKey = useMemo(
    () =>
      table
        .getVisibleLeafColumns()
        .map((c) => c.id)
        .join(","),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columnVisibility, selectionModeActive]
  );

  // Padding-based virtualization: spacer rows keep scroll height correct
  // while visible rows render in normal table flow for proper column alignment.
  const virtualItems = enableVirtualization ? virtualizer.getVirtualItems() : [];
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
      : 0;

  return (
    <div className="space-y-4">
      {helpText && typeof helpText === "function" ? helpText(table) : helpText}
      {enableRowSelection &&
        selectionModeActive &&
        table.getFilteredSelectedRowModel().rows.length > 0 && (
          <div className="text-muted-foreground text-sm">
            {t("rowsSelected", {
              selected: table.getFilteredSelectedRowModel().rows.length,
              total: table.getFilteredRowModel().rows.length,
            })}
          </div>
        )}
      <div
        className={cn(
          "overflow-hidden rounded-md border",
          selectionModeActive && "border-primary ring-primary/20 ring-2"
        )}
      >
        {enableFilterInput ||
        enableClearSorting ||
        enableColumnVisibilityDropdown ||
        enableRowSelection ? (
          <div className="flex flex-wrap items-center justify-between gap-2 p-4">
            <div className="flex flex-1 items-center gap-2">
              {enableRowSelection && (
                <Button
                  variant={selectionModeActive ? "default" : "outline"}
                  onClick={() => {
                    if (selectionModeActive) {
                      handleExitSelection();
                    } else {
                      setSelectionModeActive(true);
                    }
                  }}
                  className="shrink-0"
                >
                  {selectionModeActive ? t("exitSelection") : t("select")}
                </Button>
              )}
              {enableFilterInput && (
                <Input
                  placeholder={filterInputPlaceholder}
                  value={(table.getColumn(filterInputColumnKey)?.getFilterValue() as string) ?? ""}
                  onChange={(event) =>
                    table.getColumn(filterInputColumnKey)?.setFilterValue(event.target.value)
                  }
                  className="min-w-16 flex-1"
                />
              )}
            </div>
            <div className="ml-auto flex items-center justify-end gap-2">
              {/* Desktop: Show controls inline */}
              <div className="hidden flex-wrap items-center justify-end gap-2 md:flex">
                {enableClearSorting && (
                  <Button variant="ghost" onClick={() => table.resetSorting()}>
                    <span className="text-muted-foreground">{t("resetSorting")}</span>
                  </Button>
                )}
                {groupingEnabled && hasGroupingOptions ? (
                  <div className="flex items-center gap-2">
                    <Label
                      htmlFor={groupingSelectId}
                      className="text-muted-foreground text-sm font-medium"
                    >
                      {t("groupBy")}
                    </Label>
                    <Select
                      value={groupingSelectValue}
                      onValueChange={(value) => {
                        if (value === GROUPING_NONE_VALUE) {
                          setGrouping([]);
                        } else {
                          setGrouping([value]);
                        }
                      }}
                    >
                      <SelectTrigger id={groupingSelectId} className="w-40">
                        <SelectValue placeholder={t("chooseGrouping")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={GROUPING_NONE_VALUE}>{t("none")}</SelectItem>
                        {groupingChoices.map((option) => (
                          <SelectItem key={option.id} value={option.id}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}
                {enableColumnVisibilityDropdown && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="ml-auto">
                        {t("columns")} <ChevronDown />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {table
                        .getAllColumns()
                        .filter((column) => column.getCanHide())
                        .map((column) => {
                          return (
                            <DropdownMenuCheckboxItem
                              key={column.id}
                              className="capitalize"
                              checked={column.getIsVisible()}
                              onCheckedChange={(value) => column.toggleVisibility(!!value)}
                            >
                              {column.id}
                            </DropdownMenuCheckboxItem>
                          );
                        })}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>

              {/* Mobile: Show overflow menu */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" className="md:hidden">
                    <MoreVertical className="h-4 w-4" />
                    <span className="sr-only">{t("tableOptions")}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>{t("tableOptions")}</DropdownMenuLabel>
                  <DropdownMenuSeparator />

                  {enableRowSelection && (
                    <>
                      <DropdownMenuItem
                        onSelect={() => {
                          if (selectionModeActive) {
                            handleExitSelection();
                          } else {
                            setSelectionModeActive(true);
                          }
                        }}
                        className="cursor-pointer"
                      >
                        {selectionModeActive ? t("exitSelectionMode") : t("enableSelectionMode")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {enableClearSorting && (
                    <>
                      <DropdownMenuItem
                        onSelect={() => table.resetSorting()}
                        className="cursor-pointer"
                      >
                        {t("resetSorting")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {groupingEnabled && hasGroupingOptions && (
                    <>
                      <DropdownMenuSub>
                        <DropdownMenuSubTrigger>{t("groupBy")}</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                          <DropdownMenuCheckboxItem
                            checked={groupingSelectValue === GROUPING_NONE_VALUE}
                            onCheckedChange={() => setGrouping([])}
                          >
                            {t("none")}
                          </DropdownMenuCheckboxItem>
                          {groupingChoices.map((option) => (
                            <DropdownMenuCheckboxItem
                              key={option.id}
                              checked={groupingSelectValue === option.id}
                              onCheckedChange={() => setGrouping([option.id])}
                            >
                              {option.label}
                            </DropdownMenuCheckboxItem>
                          ))}
                        </DropdownMenuSubContent>
                      </DropdownMenuSub>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {enableColumnVisibilityDropdown && (
                    <>
                      <DropdownMenuSub>
                        <DropdownMenuSubTrigger>{t("columns")}</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                          {table
                            .getAllColumns()
                            .filter((column) => column.getCanHide())
                            .map((column) => {
                              return (
                                <DropdownMenuCheckboxItem
                                  key={column.id}
                                  className="capitalize"
                                  checked={column.getIsVisible()}
                                  onCheckedChange={(value) => column.toggleVisibility(!!value)}
                                >
                                  {column.id}
                                </DropdownMenuCheckboxItem>
                              );
                            })}
                        </DropdownMenuSubContent>
                      </DropdownMenuSub>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        ) : null}

        <Table
          scrollContainerRef={enableVirtualization ? scrollContainerRef : undefined}
          scrollContainerClassName={enableVirtualization ? virtualContainerHeight : undefined}
        >
          <TableHeader className={enableVirtualization ? "bg-card sticky top-0 z-10" : undefined}>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length ? (
              enableVirtualization ? (
                <>
                  {paddingTop > 0 && (
                    <tr>
                      <td
                        style={{ height: paddingTop, padding: 0, border: "none" }}
                        colSpan={visibleColCount}
                      />
                    </tr>
                  )}
                  {virtualItems.map((virtualRow) => {
                    const row = rows[virtualRow.index];
                    return (
                      <VirtualRow
                        key={row.id}
                        row={row}
                        virtualRow={virtualRow}
                        measureElement={virtualizer.measureElement}
                        groupingEnabled={groupingEnabled}
                        colSpan={visibleColCount}
                        rowWrapper={rowWrapper}
                        visibleColumnKey={visibleColumnKey}
                      />
                    );
                  })}
                  {paddingBottom > 0 && (
                    <tr>
                      <td
                        style={{ height: paddingBottom, padding: 0, border: "none" }}
                        colSpan={visibleColCount}
                      />
                    </tr>
                  )}
                </>
              ) : (
                rows.map((row) => {
                  if (groupingEnabled && row.getIsGrouped()) {
                    return <GroupedRow key={row.id} row={row} colSpan={visibleColCount} />;
                  }
                  const cells = row
                    .getVisibleCells()
                    .map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ));
                  if (rowWrapper) {
                    return (
                      <Fragment key={row.id}>
                        {rowWrapper({
                          row,
                          children: cells,
                        })}
                      </Fragment>
                    );
                  }
                  return (
                    <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                      {cells}
                    </TableRow>
                  );
                })
              )
            ) : (
              <TableRow>
                <TableCell colSpan={visibleColCount} className="h-24 text-center">
                  {t("noResultsDot")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        {showPagination && (
          <div className="pp4 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-sm">{t("rowsPerPage")}</span>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => {
                  const nextSize = Number(value);
                  if (Number.isFinite(nextSize) && nextSize > 0) {
                    table.setPageSize(nextSize);
                  }
                }}
              >
                <SelectTrigger className="w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  {pageSizeChoices.map((option) => (
                    <SelectItem key={option} value={String(option)}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 self-end sm:self-auto">
              {manualPagination && externalPageCount !== undefined && (
                <span className="text-muted-foreground text-sm">
                  {t("pageOf", {
                    current: table.getState().pagination.pageIndex + 1,
                    total: Math.max(externalPageCount, 1),
                  })}
                </span>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
                onMouseEnter={() => {
                  const prevIndex = table.getState().pagination.pageIndex - 1;
                  if (prevIndex >= 0 && onPrefetchPage) onPrefetchPage(prevIndex);
                }}
              >
                {t("previous")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
                onMouseEnter={() => {
                  const nextIndex = table.getState().pagination.pageIndex + 1;
                  if (table.getCanNextPage() && onPrefetchPage) onPrefetchPage(nextIndex);
                }}
              >
                {t("next")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function GroupedRow<TData>({ row, colSpan }: { row: Row<TData>; colSpan: number }) {
  const groupedCell = row.getAllCells().find((cell) => cell.getIsGrouped && cell.getIsGrouped());
  const groupContent =
    groupedCell && groupedCell.column.columnDef.cell
      ? flexRender(groupedCell.column.columnDef.cell, groupedCell.getContext())
      : ((groupedCell?.getValue() ?? row.id) as ReactNode);
  const rawGroupValue = groupedCell?.getValue();
  const groupLabelText = typeof rawGroupValue === "string" ? rawGroupValue : "grouped rows";
  const toggleExpandHandler = row.getToggleExpandedHandler?.();
  const canToggle = typeof toggleExpandHandler === "function";
  const isExpanded = row.getIsExpanded();
  return (
    <TableRow key={row.id} className="bg-muted/30" data-state="grouped">
      <TableCell colSpan={colSpan} className="font-medium">
        <div className="flex items-center gap-2">
          {canToggle ? (
            <button
              type="button"
              onClick={toggleExpandHandler}
              className="text-muted-foreground hover:text-foreground inline-flex h-6 w-6 items-center justify-center rounded-md"
              aria-label={`${isExpanded ? "Collapse" : "Expand"} ${groupLabelText}`}
            >
              <ChevronDown
                className={`h-4 w-4 transition-transform ${isExpanded ? "" : "-rotate-90"}`}
              />
            </button>
          ) : null}
          <span>{groupContent}</span>
        </div>
      </TableCell>
    </TableRow>
  );
}

/**
 * Memoized cell content for virtual rows. Only re-renders when the underlying
 * row data or selection state changes — NOT on every scroll position update.
 * This is the key performance optimization: cell renderers (Select, Checkbox,
 * TagBadge, etc.) are expensive and shouldn't run on every scroll frame.
 */
const MemoizedVirtualCells = memo(
  function VirtualCells({
    row,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    visibleColumnKey,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    isSelected,
  }: {
    row: Row<unknown>;
    visibleColumnKey: string;
    isSelected: boolean;
  }) {
    return (
      <>
        {row.getVisibleCells().map((cell) => (
          <TableCell key={cell.id}>
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </TableCell>
        ))}
      </>
    );
  },
  (prev, next) =>
    prev.row.original === next.row.original &&
    prev.isSelected === next.isSelected &&
    prev.visibleColumnKey === next.visibleColumnKey
);

function VirtualRow<TData>({
  row,
  virtualRow,
  measureElement,
  groupingEnabled,
  colSpan,
  rowWrapper,
  visibleColumnKey,
}: {
  row: Row<TData>;
  virtualRow: { index: number; start: number; size: number };
  measureElement: (el: HTMLElement | null) => void;
  groupingEnabled: boolean;
  colSpan: number;
  rowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  visibleColumnKey: string;
}) {
  if (groupingEnabled && row.getIsGrouped()) {
    return (
      <TableRow
        data-index={virtualRow.index}
        ref={measureElement}
        className="bg-muted/30"
        data-state="grouped"
      >
        <TableCell colSpan={colSpan} className="font-medium">
          <GroupedRowContent row={row} />
        </TableCell>
      </TableRow>
    );
  }

  const cells = (
    <MemoizedVirtualCells
      row={row as Row<unknown>}
      visibleColumnKey={visibleColumnKey}
      isSelected={row.getIsSelected()}
    />
  );

  if (rowWrapper) {
    return (
      <Fragment>
        {rowWrapper({
          row,
          children: cells,
          virtualIndex: virtualRow.index,
          measureRef: measureElement,
        })}
      </Fragment>
    );
  }

  return (
    <TableRow
      data-index={virtualRow.index}
      ref={measureElement}
      data-state={row.getIsSelected() && "selected"}
    >
      {cells}
    </TableRow>
  );
}

/** Renders the expand/collapse content for a grouped row. */
function GroupedRowContent<TData>({ row }: { row: Row<TData> }) {
  const groupedCell = row.getAllCells().find((cell) => cell.getIsGrouped && cell.getIsGrouped());
  const groupContent =
    groupedCell && groupedCell.column.columnDef.cell
      ? flexRender(groupedCell.column.columnDef.cell, groupedCell.getContext())
      : ((groupedCell?.getValue() ?? row.id) as ReactNode);
  const rawGroupValue = groupedCell?.getValue();
  const groupLabelText = typeof rawGroupValue === "string" ? rawGroupValue : "grouped rows";
  const toggleExpandHandler = row.getToggleExpandedHandler?.();
  const canToggle = typeof toggleExpandHandler === "function";
  const isExpanded = row.getIsExpanded();
  return (
    <div className="flex items-center gap-2">
      {canToggle ? (
        <button
          type="button"
          onClick={toggleExpandHandler}
          className="text-muted-foreground hover:text-foreground inline-flex h-6 w-6 items-center justify-center rounded-md"
          aria-label={`${isExpanded ? "Collapse" : "Expand"} ${groupLabelText}`}
        >
          <ChevronDown
            className={`h-4 w-4 transition-transform ${isExpanded ? "" : "-rotate-90"}`}
          />
        </button>
      ) : null}
      <span>{groupContent}</span>
    </div>
  );
}
