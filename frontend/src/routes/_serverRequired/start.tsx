import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export interface StartSearch {
  invite_code?: string;
}

export const validateStartSearch = (search: Record<string, unknown>): StartSearch =>
  typeof search.invite_code === "string" && search.invite_code.trim()
    ? { invite_code: search.invite_code.trim() }
    : {};

export const Route = createFileRoute("/_serverRequired/start")({
  validateSearch: validateStartSearch,
  component: lazyRouteComponent(() =>
    import("@/pages/StartPage").then((m) => ({ default: m.StartPage }))
  ),
});
