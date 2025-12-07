"use client";

import { Fragment, type ReactNode, useMemo, useRef, useState, useId, useEffect } from "react";
import {
  ColumnDef,
  Row,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
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
import { ChevronDown } from "lucide-react";

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
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
}

export interface DataTableRowWrapperProps<TData> {
  row: Row<TData>;
  children: ReactNode;
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
}: DataTableProps<TData, TValue>) {
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
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onGroupingChange: groupingEnabled ? setGrouping : undefined,
    onPaginationChange: enablePagination ? setPagination : undefined,
    getPaginationRowModel: enablePagination ? getPaginationRowModel() : undefined,
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getGroupedRowModel: groupingEnabled ? getGroupedRowModel() : undefined,
    getExpandedRowModel: groupingEnabled ? getExpandedRowModel() : undefined,
    initialState: computedInitialState,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      ...(groupingEnabled ? { grouping } : {}),
      ...(enablePagination ? { pagination } : {}),
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

  return (
    <div className="space-y-4">
      {helpText && typeof helpText === "function" ? helpText(table) : helpText}
      <div className="overflow-hidden rounded-md border">
        {enableFilterInput || enableClearSorting || enableColumnVisibilityDropdown ? (
          <div className="flex flex-wrap items-center justify-between gap-2 p-4">
            <div className="flex items-center gap-2">
              {enableFilterInput && (
                <Input
                  placeholder={filterInputPlaceholder}
                  value={(table.getColumn(filterInputColumnKey)?.getFilterValue() as string) ?? ""}
                  onChange={(event) =>
                    table.getColumn(filterInputColumnKey)?.setFilterValue(event.target.value)
                  }
                  className="max-w-sm min-w-16"
                />
              )}
            </div>
            <div className="flex items-center gap-2">
              {enableClearSorting && (
                <Button variant="ghost" onClick={() => table.resetSorting()}>
                  <span className="text-muted-foreground">Reset Sorting</span>
                </Button>
              )}
              {groupingEnabled && hasGroupingOptions ? (
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor={groupingSelectId}
                    className="text-muted-foreground text-sm font-medium"
                  >
                    Group by
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
                      <SelectValue placeholder="Choose grouping" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={GROUPING_NONE_VALUE}>None</SelectItem>
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
                      Columns <ChevronDown />
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
          </div>
        ) : null}

        <Table>
          <TableHeader>
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
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => {
                if (groupingEnabled && row.getIsGrouped()) {
                  const groupedCell = row
                    .getAllCells()
                    .find((cell) => cell.getIsGrouped && cell.getIsGrouped());
                  const groupContent =
                    groupedCell && groupedCell.column.columnDef.cell
                      ? flexRender(groupedCell.column.columnDef.cell, groupedCell.getContext())
                      : ((groupedCell?.getValue() ?? row.id) as ReactNode);
                  const rawGroupValue = groupedCell?.getValue();
                  const groupLabelText =
                    typeof rawGroupValue === "string" ? rawGroupValue : "grouped rows";
                  const toggleExpandHandler = row.getToggleExpandedHandler?.();
                  const canToggle = typeof toggleExpandHandler === "function";
                  const isExpanded = row.getIsExpanded();
                  return (
                    <TableRow key={row.id} className="bg-muted/30" data-state="grouped">
                      <TableCell
                        colSpan={table.getVisibleLeafColumns().length || columns.length}
                        className="font-medium"
                      >
                        <div className="flex items-center gap-2">
                          {canToggle ? (
                            <button
                              type="button"
                              onClick={toggleExpandHandler}
                              className="text-muted-foreground hover:text-foreground inline-flex h-6 w-6 items-center justify-center rounded-md"
                              aria-label={`${isExpanded ? "Collapse" : "Expand"} ${groupLabelText}`}
                            >
                              <ChevronDown
                                className={`h-4 w-4 transition-transform ${
                                  isExpanded ? "" : "-rotate-90"
                                }`}
                              />
                            </button>
                          ) : null}
                          <span>{groupContent}</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
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
            ) : (
              <TableRow>
                <TableCell
                  colSpan={table.getVisibleLeafColumns().length || columns.length}
                  className="h-24 text-center"
                >
                  No results.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        {enablePagination && (
          <div className="pp4 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-sm">Rows per page:</span>
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
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
