import { createFileRoute, redirect } from "@tanstack/react-router";

import { validateStartSearch } from "./start";

/** Signing up starts at `/start`; an invite in the address goes with it. */
export const Route = createFileRoute("/_serverRequired/register")({
  validateSearch: validateStartSearch,
  beforeLoad: ({ search }) => {
    throw redirect({ to: "/start", search, replace: true });
  },
});
