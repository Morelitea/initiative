import { HttpResponse } from "msw";

import { guildHttp } from "../guildHttp";

/**
 * Every tool's "how many of you are in each initiative?" is one request.
 * Nothing by default: a surface that shows the numbers renders zeros unless a
 * test says otherwise, and none of them warn about an unhandled call.
 */
export const toolCountHandlers = [
  guildHttp.get("/tools/counts/by-initiative", () => HttpResponse.json({ counts: {} })),
];
