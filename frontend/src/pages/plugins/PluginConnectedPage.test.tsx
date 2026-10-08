/**
 * Where a person lands when a connection's vendor flow ends: one word in the
 * address, one sentence on the page.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { PluginConnectedPage } from "./PluginConnectedPage";

describe("PluginConnectedPage", () => {
  it("asks the person to finish where they are signed in", async () => {
    renderPage(PluginConnectedPage, { routerSearch: { outcome: "sign_in_required" } });

    expect(
      await screen.findByText(
        "Finish connecting in the browser where you're signed in to Initiative, as the person who started it."
      )
    ).toBeInTheDocument();
  });

  it("reads an ending it does not know as expired", async () => {
    renderPage(PluginConnectedPage, { routerSearch: { outcome: "whatever" } });

    expect(await screen.findByText("That link has expired")).toBeInTheDocument();
  });
});
