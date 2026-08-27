import { HttpResponse } from "msw";

import { buildDefaultFilterPresets, buildFilterPreset } from "@/__tests__/factories";

import { guildHttp } from "../guildHttp";

export const filterPresetHandlers = [
  guildHttp.get("/projects/:projectId/filter-presets/", ({ params }) => {
    return HttpResponse.json({
      items: buildDefaultFilterPresets(Number(params.projectId)),
      can_manage: true,
    });
  }),

  guildHttp.post("/projects/:projectId/filter-presets/", async ({ request }) => {
    const body = (await request.json()) as { name: string; is_default?: boolean };
    return HttpResponse.json(
      buildFilterPreset({ name: body.name, slug: "saved-view", is_default: body.is_default }),
      { status: 201 }
    );
  }),

  guildHttp.patch("/projects/:projectId/filter-presets/:presetId", () =>
    HttpResponse.json(buildFilterPreset())
  ),

  guildHttp.post("/projects/:projectId/filter-presets/reorder", () =>
    HttpResponse.json(buildDefaultFilterPresets())
  ),

  guildHttp.delete(
    "/projects/:projectId/filter-presets/:presetId",
    () => new HttpResponse(null, { status: 204 })
  ),
];
