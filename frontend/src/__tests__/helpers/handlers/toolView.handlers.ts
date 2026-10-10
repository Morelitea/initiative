import { HttpResponse } from "msw";

import { buildSavedViewSet, buildToolViewSet } from "@/__tests__/factories";
import type { ToolViewSetWrite } from "@/api/generated/initiativeAPI.schemas";

import { communityHttp } from "../communityHttp";

export const toolViewHandlers = [
  communityHttp.get("/views/", () => HttpResponse.json(buildToolViewSet())),

  communityHttp.put("/views/", async ({ request }) =>
    HttpResponse.json(buildSavedViewSet((await request.json()) as ToolViewSetWrite))
  ),

  communityHttp.delete("/views/", () => new HttpResponse(null, { status: 204 })),
];
