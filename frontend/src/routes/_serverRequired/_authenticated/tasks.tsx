import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/tasks")({
  beforeLoad: ({ location }) => {
    // Only redirect if we're at exactly /tasks, not a child route like /tasks/123
    if (location.pathname === "/tasks" || location.pathname === "/tasks/") {
      throw redirect({ to: "/" });
    }
  },
});
