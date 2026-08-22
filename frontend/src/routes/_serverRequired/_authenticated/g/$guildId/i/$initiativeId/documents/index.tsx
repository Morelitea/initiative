import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { validateInitiativeToolSearch } from "@/lib/routeSearch";

const InitiativeDetailPage = lazyRouteComponent(() =>
  import("@/pages/InitiativeDetailPage").then((m) => ({ default: m.InitiativeDetailPage }))
);

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/documents/"
)({
  validateSearch: validateInitiativeToolSearch,
  component: () => <InitiativeDetailPage tool={Tool.document} />,
});
