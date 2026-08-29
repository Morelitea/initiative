import { HttpResponse } from "msw";

import { guildHttp } from "../guildHttp";

/**
 * Every tool answers "how many of you are in each initiative?" at the same
 * address. Nothing by default: a surface that shows the numbers renders zeros
 * unless a test says otherwise, and none of them warn about an unhandled call.
 */
const COUNT_PATHS = [
  "/projects",
  "/documents",
  "/queues",
  "/counter-groups",
  "/calendars",
  "/dashboards",
];

export const toolCountHandlers = COUNT_PATHS.map((path) =>
  guildHttp.get(`${path}/counts/by-initiative`, () => HttpResponse.json({ counts: {} }))
);
