import { HttpResponse } from "msw";

import { buildSavedLayoutSet, buildToolLayoutSet } from "@/__tests__/factories";
import type { DetailLayoutWrite, ListLayoutWrite } from "@/api/generated/initiativeAPI.schemas";

import { communityHttp } from "../communityHttp";

export const toolLayoutHandlers = [
  communityHttp.get("/layouts/", () => HttpResponse.json(buildToolLayoutSet())),

  communityHttp.put("/layouts/", async ({ request }) =>
    HttpResponse.json(
      buildSavedLayoutSet(
        buildToolLayoutSet(),
        (await request.json()) as ListLayoutWrite | DetailLayoutWrite
      )
    )
  ),

  communityHttp.delete("/layouts/:kind", () => HttpResponse.json(buildToolLayoutSet())),
];
