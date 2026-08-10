import { screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { MemberMultiSelect, MemberSelect } from "./MemberSearchSelect";

const ADA = {
  id: 42,
  full_name: "Ada Lovelace",
  avatar_url: null,
  avatar_base64: null,
  status: "active",
};
const GRACE = {
  id: 43,
  full_name: "Grace Hopper",
  avatar_url: null,
  avatar_base64: null,
  status: "active",
};

const ROSTER = [ADA, GRACE];

/** The project member typeahead, honouring the `user_id` lookup filter the
 *  pickers use to resolve a selection they were handed as bare ids. */
const memberSearchHandler = (onRequest?: (ids: string[]) => void) =>
  guildHttp.get("/projects/:projectId/members/search", ({ request }) => {
    const ids = new URL(request.url).searchParams.getAll("user_id");
    onRequest?.(ids);
    const items = ids.length ? ROSTER.filter((user) => ids.includes(String(user.id))) : ROSTER;
    return HttpResponse.json({
      items,
      total_count: items.length,
      page: 1,
      page_size: 25,
      has_next: false,
      has_prev: false,
    });
  });

describe("MemberMultiSelect", () => {
  it("names a selection it was given as bare ids", async () => {
    server.use(memberSearchHandler());

    renderWithProviders(
      <MemberMultiSelect
        variant="filter"
        scope={{ type: "project", projectId: 7 }}
        selectedIds={[ADA.id]}
        onChange={() => {}}
        placeholder="All assignees"
      />
    );

    // The trigger starts on the id fallback, then resolves to the real name.
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByText(`User #${ADA.id}`)).not.toBeInTheDocument();
  });

  it("only looks up the ids it cannot already name", async () => {
    const lookups: string[][] = [];
    server.use(memberSearchHandler((ids) => ids.length && lookups.push(ids)));

    renderWithProviders(
      <MemberMultiSelect
        variant="filter"
        scope={{ type: "project", projectId: 7 }}
        selectedIds={[ADA.id, GRACE.id]}
        selectedUsers={[GRACE]}
        onChange={() => {}}
      />
    );

    await screen.findByText("2 selected");
    await waitFor(() => expect(lookups.length).toBeGreaterThan(0));
    // Grace came in via `selectedUsers`; only Ada needs resolving.
    expect(lookups[0]).toEqual([String(ADA.id)]);
  });

  it("falls back to the id when the selection is not in the scoped roster", async () => {
    server.use(memberSearchHandler());

    renderWithProviders(
      <MemberMultiSelect
        variant="filter"
        scope={{ type: "project", projectId: 7 }}
        selectedIds={[999]}
        onChange={() => {}}
      />
    );

    expect(await screen.findByText("User #999")).toBeInTheDocument();
  });
});

describe("MemberSelect", () => {
  it("names a value it was given as a bare id", async () => {
    server.use(memberSearchHandler());

    renderWithProviders(
      <MemberSelect
        scope={{ type: "project", projectId: 7 }}
        value={GRACE.id}
        onChange={() => {}}
      />
    );

    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.queryByText(`User #${GRACE.id}`)).not.toBeInTheDocument();
  });
});
