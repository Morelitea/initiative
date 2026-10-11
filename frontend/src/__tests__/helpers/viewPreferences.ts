import { HttpResponse, http } from "msw";

import { server } from "@/__tests__/helpers/msw-server";

/**
 * A server that keeps this reader's view preferences as they save them, the
 * way the real one does, so a list opened again (a fresh query client) finds
 * what they left. Returns what is kept, by key.
 */
export const keepViewPreferences = (): Record<string, unknown> => {
  const kept: Record<string, unknown> = {};
  server.use(
    http.get("/api/v1/user-view-preferences", () => HttpResponse.json({ items: { ...kept } })),
    http.put("/api/v1/user-view-preferences/:scopeKey", async ({ params, request }) => {
      kept[String(params.scopeKey)] = ((await request.json()) as { value: unknown }).value;
      return HttpResponse.json({});
    })
  );
  return kept;
};
