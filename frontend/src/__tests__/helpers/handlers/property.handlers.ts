import { HttpResponse } from "msw";

import { buildPropertyDefinition } from "@/__tests__/factories/properties";

import { guildHttp } from "../guildHttp";

/**
 * Default MSW handlers for the property endpoints.
 *
 * These provide permissive defaults so components can render without
 * explicit setup; individual tests override via `server.use(...)` when
 * they need to assert on specific request bodies or inject fixtures.
 */
export const propertyHandlers = [
  // ── Property definitions ──────────────────────────────────────────────────
  guildHttp.get("/property-definitions/", () => {
    return HttpResponse.json([]);
  }),

  guildHttp.post("/property-definitions/", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      buildPropertyDefinition({
        name: (body.name as string) ?? "New property",
        type: (body.type as never) ?? "text",
        initiative_id: typeof body.initiative_id === "number" ? body.initiative_id : 1,
        options: (body.options as never) ?? null,
      })
    );
  }),

  guildHttp.get("/property-definitions/:definitionId", ({ params }) => {
    const id = Number(params.definitionId);
    return HttpResponse.json(buildPropertyDefinition({ id }));
  }),

  guildHttp.patch("/property-definitions/:definitionId", async ({ params, request }) => {
    const id = Number(params.definitionId);
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      definition: buildPropertyDefinition({
        id,
        ...(body as Partial<ReturnType<typeof buildPropertyDefinition>>),
      }),
      orphaned_value_count: 0,
    });
  }),

  guildHttp.delete("/property-definitions/:definitionId", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  guildHttp.get("/property-definitions/:definitionId/entities", () => {
    return HttpResponse.json({ tasks: [], documents: [] });
  }),

  // ── Attach values ─────────────────────────────────────────────────────────
  // The components under test only care that the request goes through; the
  // returned payload is ignored beyond invalidation, so we use loose shapes.
  guildHttp.put("/documents/:documentId/properties", ({ params }) => {
    const id = Number(params.documentId);
    return HttpResponse.json({ id, properties: [] });
  }),

  guildHttp.put("/tasks/:taskId/properties", ({ params }) => {
    const id = Number(params.taskId);
    return HttpResponse.json({ id, properties: [] });
  }),
];
