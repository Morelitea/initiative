import { useCallback, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";

export interface UsePaginationOptions {
  defaultPageSize?: number;
  syncWithUrl?: boolean;
}

export interface PaginationState {
  page: number;
  pageSize: number;
  setPage: (updater: number | ((prev: number) => number)) => void;
  setPageSize: (size: number) => void;
  resetPage: () => void;
}

export function usePagination(options?: UsePaginationOptions): PaginationState {
  const { defaultPageSize = 20, syncWithUrl = true } = options ?? {};
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const [page, setPageState] = useState(() => (syncWithUrl ? (searchParams.page ?? 1) : 1));
  const [pageSize, setPageSizeState] = useState(defaultPageSize);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        if (syncWithUrl) {
          void router.navigate({
            to: ".",
            search: {
              ...searchParamsRef.current,
              page: next <= 1 ? undefined : next,
            },
            replace: true,
          });
        }
        return next;
      });
    },
    [router, syncWithUrl]
  );

  const setPageSize = useCallback(
    (size: number) => {
      setPageSizeState(size);
      setPage(1);
    },
    [setPage]
  );

  const resetPage = useCallback(() => {
    setPage(1);
  }, [setPage]);

  return { page, pageSize, setPage, setPageSize, resetPage };
}
