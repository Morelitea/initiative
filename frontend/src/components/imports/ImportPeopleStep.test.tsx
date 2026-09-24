/**
 * Who an import's people step offers each name to.
 *
 * The community's admin, or its seat, matches a name to any member. Anybody
 * else is offered themselves or nobody — the only answers the confirm takes
 * from them.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { GuildRole } from "@/api/generated/initiativeAPI.schemas";

import { ImportPeopleStep, type PlanPerson } from "./ImportPeopleStep";

const person: PlanPerson = {
  handle: "stranger#4321",
  name: "Alice Chen",
  comment_count: 1,
  suggested_user_id: null,
};

function renderStep(role: GuildRole, value: Record<string, number | null>, onChange = vi.fn()) {
  const me = buildUser({ id: 9 });
  renderWithProviders(<ImportPeopleStep people={[person]} value={value} onChange={onChange} />, {
    auth: { user: me },
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
  });
  return { me, onChange };
}

describe("ImportPeopleStep", () => {
  it("offers a member themselves or nobody", async () => {
    const { onChange } = renderStep("member", {});

    expect(screen.getByText(/only a community admin can match names/i)).toBeInTheDocument();
    const picker = screen.getByRole("combobox", { name: /who alice chen is here/i });
    expect(picker).toHaveTextContent(/nobody here/i);

    await userEvent.click(picker);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["Nobody here", "Me"]);

    await userEvent.click(screen.getByRole("option", { name: "Me" }));
    expect(onChange).toHaveBeenCalledWith({ "stranger#4321": 9 });
  });

  it("shows a member's own answer as Me", () => {
    renderStep("member", { "stranger#4321": 9 });

    expect(screen.getByRole("combobox", { name: /who alice chen is here/i })).toHaveTextContent(
      "Me"
    );
  });

  it("offers an admin the whole community", () => {
    renderStep("admin", {});

    expect(screen.getByText(/pick who each person is here/i)).toBeInTheDocument();
    expect(screen.queryByText(/only a community admin can match names/i)).not.toBeInTheDocument();
  });
});
