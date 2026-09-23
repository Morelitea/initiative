import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppErrorBoundary } from "@/components/errors/AppErrorBoundary";
import { router as appRouter } from "@/router";

/**
 * A small tree under the app router's own defaults: a layout, a page that
 * throws whatever `failure` returns, and nothing at any other address.
 */
function renderAt(path: string, failure: () => unknown) {
  const rootRoute = createRootRoute({
    component: () => (
      <div data-testid="shell">
        <Outlet />
      </div>
    ),
  });
  const Broken = () => {
    const thrown = failure();
    if (thrown !== undefined) {
      throw thrown;
    }
    return <p>page content</p>;
  };
  const routeTree = rootRoute.addChildren([
    createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => <p>home</p> }),
    createRoute({ getParentRoute: () => rootRoute, path: "/broken", component: Broken }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    defaultErrorComponent: appRouter.options.defaultErrorComponent,
    defaultNotFoundComponent: appRouter.options.defaultNotFoundComponent,
  });
  return render(<RouterProvider router={router} />);
}

describe("app error pages", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the error page inside the shell when a page fails to render", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderAt("/broken", () => new Error("boom"));

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to My Tasks" })).toHaveAttribute("href", "/");
    expect(screen.getByText(/Error: boom/)).toBeInTheDocument();
  });

  it("renders the page again after a successful retry", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let failing = true;
    renderAt("/broken", () => (failing ? new Error("boom") : undefined));

    await screen.findByText("Something went wrong");
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("page content")).toBeInTheDocument();
  });

  it("offers a reload when the page's code is from an older release", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderAt(
      "/broken",
      () => new TypeError("Failed to fetch dynamically imported module: /assets/Page-abc.js")
    );

    expect(await screen.findByText("Initiative has been updated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("shows the not-found page for an address with nothing behind it", async () => {
    renderAt("/no/such/place", () => undefined);

    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toBeInTheDocument();
  });
});

describe("AppErrorBoundary", () => {
  it("replaces a failed app with a reload screen", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Crash = () => {
      throw new Error("provider failed");
    };

    render(
      <AppErrorBoundary>
        <Crash />
      </AppErrorBoundary>
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
