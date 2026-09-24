import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUserSummary } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { TaskDescription } from "./TaskDescription";

describe("a task's description", () => {
  it("reads a mentioned person as who they are now, linked to their profile", async () => {
    server.use(
      http.get("*/api/v1/g/:guildId/users/search", () =>
        HttpResponse.json({
          items: [
            buildUserSummary({ id: 12, username: "ada", discriminator: 7, full_name: "Ada King" }),
          ],
          total: 1,
          page: 1,
          page_size: 100,
        })
      )
    );

    renderPage(() => <TaskDescription content="Pair with @[Ada Lovelace](12) on this." />);

    const link = await screen.findByRole("link", { name: "@Ada King" });
    expect(link).toHaveAttribute("href", "/u/ada0007");
  });

  it("links a mentioned thing rather than a bare number", async () => {
    renderPage(() => <TaskDescription content="Blocked on #task[Fix login](3)." />);

    const link = await screen.findByRole("link", { name: /Fix login/ });
    expect(link.getAttribute("href")).not.toBe("3");
  });

  it("keeps the rest of the markdown", async () => {
    const { container } = renderPage(() => <TaskDescription content="Ship **now**" />);

    expect((await screen.findByText("now")).tagName).toBe("STRONG");
    expect(container.querySelector("a")).toBeNull();
  });
});
