import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildGuild, buildInitiative } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { CreateInitiativeDialog } from "./CreateInitiativeDialog";

/** Records each creation payload, so a submit can be read field by field. */
function stubCreate() {
  const creations: unknown[] = [];
  server.use(
    guildHttp.post("/initiatives/", async ({ request }) => {
      const body = await request.json();
      creations.push(body);
      return HttpResponse.json(buildInitiative({ name: "Skunkworks" }), { status: 201 });
    })
  );
  return creations;
}

const renderDialog = () =>
  renderPage(() => <CreateInitiativeDialog open onOpenChange={vi.fn()} />, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
  });

describe("CreateInitiativeDialog", () => {
  it("exposes the join policy and sends the chosen one", async () => {
    const creations = stubCreate();

    renderDialog();

    // Every way in is on offer, with the closed default preselected.
    expect(await screen.findByRole("radio", { name: /Invite only/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /By request/ })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Name/), "Skunkworks");
    await userEvent.click(screen.getByRole("radio", { name: /Anyone can join/ }));
    await userEvent.click(screen.getByRole("button", { name: /Create initiative/i }));

    await waitFor(() => expect(creations).toHaveLength(1));
    expect(creations[0]).toMatchObject({ name: "Skunkworks", join_policy: "open" });
  });

  it("creates an initiative people have to ask to join", async () => {
    const creations = stubCreate();

    renderDialog();

    await userEvent.type(await screen.findByLabelText(/Name/), "Vanguard");
    await userEvent.click(screen.getByRole("radio", { name: /By request/ }));
    await userEvent.click(screen.getByRole("button", { name: /Create initiative/i }));

    await waitFor(() => expect(creations).toHaveLength(1));
    expect(creations[0]).toMatchObject({ name: "Vanguard", join_policy: "request" });
  });

  it("defaults the policy to private when left untouched", async () => {
    const creations = stubCreate();

    renderDialog();

    await userEvent.type(await screen.findByLabelText(/Name/), "Quiet corner");
    await userEvent.click(screen.getByRole("button", { name: /Create initiative/i }));

    await waitFor(() => expect(creations).toHaveLength(1));
    expect(creations[0]).toMatchObject({ name: "Quiet corner", join_policy: "private" });
  });
});
