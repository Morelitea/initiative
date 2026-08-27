/**
 * The directory's filters, now that they live in the app's sidebar.
 *
 * They sit on the other side of the layout from the cards they narrow, so the
 * address is what carries them across — which makes "did the filter reach the
 * URL" the thing worth asserting here, and leaves "did the grid narrow" to the
 * page's own tests. A shelf also has to carry the search along rather than
 * clearing it: picking a category while searching is a narrowing, not a reset.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";

import { CommunityDirectorySidebar } from "./CommunityDirectorySidebar";

const setup = (search: Record<string, unknown> = {}) =>
  renderPage(
    () => (
      <SidebarProvider>
        <CommunityDirectorySidebar />
      </SidebarProvider>
    ),
    { initialRoute: "/communities", routerSearch: search }
  );

const addressSearch = (router: ReturnType<typeof setup>["router"]) =>
  router.state.location.search as { q?: string; category?: string };

describe("the community directory's sidebar", () => {
  it("puts what was typed in the address, once typing settles", async () => {
    const { router } = setup();

    await userEvent.type(await screen.findByLabelText("Search communities"), "dice");

    await waitFor(() => expect(addressSearch(router).q).toBe("dice"));
  });

  it("starts from the search the address arrived with", async () => {
    setup({ q: "dice" });

    expect(await screen.findByLabelText("Search communities")).toHaveValue("dice");
  });

  it("keeps the search when a shelf is picked", async () => {
    const { router } = setup({ q: "dice" });

    await userEvent.click(await screen.findByRole("link", { name: "Tabletop RPG" }));

    await waitFor(() => expect(addressSearch(router).category).toBe("ttrpg"));
    expect(addressSearch(router).q).toBe("dice");
  });

  it("drops back to every shelf without losing the search", async () => {
    const { router } = setup({ q: "dice", category: "ttrpg" });

    await userEvent.click(await screen.findByRole("link", { name: "All" }));

    await waitFor(() => expect(addressSearch(router).category).toBeUndefined());
    expect(addressSearch(router).q).toBe("dice");
  });

  it("marks the shelf that is showing", async () => {
    setup({ category: "ttrpg" });

    expect(await screen.findByRole("link", { name: "Tabletop RPG" })).toHaveAttribute(
      "data-active",
      "true"
    );
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("data-active", "false");
  });
});
