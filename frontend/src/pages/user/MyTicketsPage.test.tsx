/**
 * The reader's own tickets, each leading to its own page.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { FiledTicketList } from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({ list: undefined as FiledTicketList | undefined }));

vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useFiledTickets: () => ({ data: state.list, isLoading: false, isError: false }),
  };
});

import { MyTicketsPage } from "./MyTicketsPage";

const now = new Date().toISOString();

const open = () =>
  renderPage(MyTicketsPage, { initialRoute: "/my-tickets/", auth: { user: buildUser() } });

describe("MyTicketsPage", () => {
  beforeEach(() => {
    state.list = undefined;
  });

  it("lists each ticket with where it stands", async () => {
    state.list = {
      items: [
        {
          task_id: 7,
          stream: "support",
          subject: "Lost my phone",
          state: "waiting_on_you",
          opened_at: now,
          updated_at: now,
        },
        {
          task_id: 9,
          stream: "feedback",
          subject: null,
          state: "closed",
          opened_at: now,
          updated_at: null,
        },
      ],
    };
    open();
    const link = await screen.findByRole("link", { name: /Lost my phone/ });
    expect(link).toHaveAttribute("href", "/my-tickets/7");
    expect(screen.getByText("Waiting on you")).toBeInTheDocument();
    // An untitled ticket goes by its kind.
    expect(screen.getByRole("link", { name: /Feedback/ })).toHaveAttribute("href", "/my-tickets/9");
  });

  it("explains an empty list", async () => {
    state.list = { items: [] };
    open();
    expect(await screen.findByText(/haven't filed any tickets/)).toBeInTheDocument();
  });
});
