import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  buildRecentCounterGroupItem,
  buildRecentDocumentItem,
  buildRecentProjectItem,
  buildRecentQueueItem,
} from "@/__tests__/factories/recent.factory";
import { renderWithProviders } from "@/__tests__/helpers/render";

// Mock the TanStack Router ``Link`` to a plain anchor so we don't need a
// router context just to verify the href shape. The component is purely
// presentational; routing semantics belong to integration tests.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, className }: { to: string; children: ReactNode; className?: string }) => (
    <a href={to} className={className}>
      {children}
    </a>
  ),
}));

import { RecentTabsBar } from "./RecentTabsBar";

describe("RecentTabsBar", () => {
  it("renders nothing when there are no items and we're not loading", () => {
    const { container } = renderWithProviders(
      <RecentTabsBar items={[]} loading={false} onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders one tab per item with its name and entity-specific icons", () => {
    const items = [
      buildRecentProjectItem({ name: "Lost Mines", icon: "⚒️" }),
      buildRecentDocumentItem({ name: "Session Notes" }),
      buildRecentQueueItem({ name: "Combat" }),
      buildRecentCounterGroupItem({ name: "HP Trackers" }),
    ];
    renderWithProviders(<RecentTabsBar items={items} onClose={() => {}} />);

    expect(screen.getByText("Lost Mines")).toBeInTheDocument();
    expect(screen.getByText("Session Notes")).toBeInTheDocument();
    expect(screen.getByText("Combat")).toBeInTheDocument();
    expect(screen.getByText("HP Trackers")).toBeInTheDocument();
    // Project emoji icon should be rendered alongside the name.
    expect(screen.getByText("⚒️")).toBeInTheDocument();
  });

  it("links each item to its guild-scoped detail page", () => {
    const items = [
      buildRecentProjectItem({ entity_id: 11, name: "ProjectX" }),
      buildRecentDocumentItem({ entity_id: 22, name: "DocY" }),
      buildRecentQueueItem({ entity_id: 33, name: "QueueZ" }),
      buildRecentCounterGroupItem({ entity_id: 44, name: "GroupW" }),
    ];
    renderWithProviders(<RecentTabsBar items={items} onClose={() => {}} />);

    expect(screen.getByRole("link", { name: /ProjectX/ })).toHaveAttribute(
      "href",
      "/g/1/projects/11"
    );
    expect(screen.getByRole("link", { name: /DocY/ })).toHaveAttribute("href", "/g/1/documents/22");
    expect(screen.getByRole("link", { name: /QueueZ/ })).toHaveAttribute("href", "/g/1/queues/33");
    expect(screen.getByRole("link", { name: /GroupW/ })).toHaveAttribute(
      "href",
      "/g/1/counter-groups/44"
    );
  });

  it("dispatches onClose with the item when the X is clicked", async () => {
    const onClose = vi.fn();
    const queue = buildRecentQueueItem({ entity_id: 7, name: "Combat" });
    renderWithProviders(<RecentTabsBar items={[queue]} onClose={onClose} />);

    const closeButton = screen.getByLabelText(/close/i);
    await userEvent.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith(queue);
  });
});
