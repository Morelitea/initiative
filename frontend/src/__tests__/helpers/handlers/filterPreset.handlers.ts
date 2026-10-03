import { HttpResponse } from "msw";

import { buildDefaultFilterPresets, buildFilterPreset } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const filterPresetHandlers = [
  communityHttp.get("/projects/:projectId/filter-presets/", ({ params }) => {
    return HttpResponse.json({
      items: buildDefaultFilterPresets(Number(params.projectId)),
      can_manage: true,
    });
  }),

  communityHttp.post("/projects/:projectId/filter-presets/", async ({ request }) => {
    const body = (await request.json()) as { name: string; is_default?: boolean };
    return HttpResponse.json(
      buildFilterPreset({ name: body.name, slug: "saved-view", is_default: body.is_default }),
      { status: 201 }
    );
  }),

  communityHttp.patch("/projects/:projectId/filter-presets/:presetId", () =>
    HttpResponse.json(buildFilterPreset())
  ),

  communityHttp.post("/projects/:projectId/filter-presets/reorder", () =>
    HttpResponse.json(buildDefaultFilterPresets())
  ),

  communityHttp.delete(
    "/projects/:projectId/filter-presets/:presetId",
    () => new HttpResponse(null, { status: 204 })
  ),
];
