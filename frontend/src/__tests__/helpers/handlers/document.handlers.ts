import { http, HttpResponse } from "msw";

export const documentHandlers = [
  http.get("/api/v1/documents/", () => {
    return HttpResponse.json({
      items: [],
      total_count: 0,
      page: 1,
      page_size: 20,
      has_next: false,
      sort_by: null,
      sort_dir: null,
    });
  }),
];
