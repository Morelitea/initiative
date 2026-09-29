interface PageFields {
  total_count: number;
  page: number;
  page_size: number;
  has_next: boolean;
  has_prev: boolean;
}

/** One page holding every item given: the envelope a paginated list returns. */
export function buildPage<T>(items: T[], overrides: Partial<PageFields> = {}) {
  return {
    items,
    total_count: items.length,
    page: 1,
    page_size: 20,
    has_next: false,
    has_prev: false,
    ...overrides,
  };
}
