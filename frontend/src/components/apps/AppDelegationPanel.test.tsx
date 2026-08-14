/**
 * The member's own answer to whether an app may act as them.
 *
 * Three states worth telling apart, and the panel says something different for
 * each: never asked, allowed (at one of two depths), and stopped. The last two
 * both read as "not allowed" to the server, but a member who withdrew has done
 * something and should see that they did.
 *
 * What the panel never offers is a way to answer for somebody else — there is
 * no user id anywhere in it.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { AppDelegation } from "@/api/appConnections";
import { TooltipProvider } from "@/components/ui/tooltip";

import { AppDelegationPanel } from "./AppDelegationPanel";

const grant = vi.fn();
const revoke = vi.fn();

vi.mock("@/hooks/useGuildAppDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuildAppDetail")>()),
  useGrantAppDelegation: () => ({ mutateAsync: grant, isPending: false }),
  useRevokeAppDelegation: () => ({ mutateAsync: revoke, isPending: false }),
}));

const render = (delegation: AppDelegation | null) =>
  renderPage(() => (
    <TooltipProvider>
      <AppDelegationPanel appId={3} appName="Auto" delegation={delegation} />
    </TooltipProvider>
  ));

const never: AppDelegation = {
  granted: false,
  can_read: false,
  can_write: false,
};

beforeEach(() => {
  grant.mockReset().mockResolvedValue(undefined);
  revoke.mockReset().mockResolvedValue(undefined);
});

describe("AppDelegationPanel", () => {
  it("offers both depths to somebody who has never been asked", async () => {
    render(never);
    expect(await screen.findByText("Not allowed")).toBeInTheDocument();
    expect(screen.getByText("Let it read as me")).toBeInTheDocument();
    expect(screen.getByText("Let it read and write as me")).toBeInTheDocument();
  });

  it("asks for reads and writes separately", async () => {
    render(never);
    fireEvent.click(await screen.findByText("Let it read as me"));
    await waitFor(() => expect(grant).toHaveBeenCalledWith(false));

    grant.mockClear();
    fireEvent.click(screen.getByText("Let it read and write as me"));
    await waitFor(() => expect(grant).toHaveBeenCalledWith(true));
  });

  it("reports the depth actually in force", async () => {
    render({ ...never, granted: true, can_read: true, can_write: false });
    expect(await screen.findByText("Can read as you")).toBeInTheDocument();

    render({ ...never, granted: true, can_read: true, can_write: true });
    expect(await screen.findAllByText("Can read and write as you")).not.toHaveLength(0);
  });

  it("lets a member take it back", async () => {
    render({ ...never, granted: true, can_read: true, can_write: true });
    fireEvent.click(await screen.findByText("Stop it acting as me"));
    await waitFor(() => expect(revoke).toHaveBeenCalled());
  });

  it("tells somebody who withdrew apart from somebody never asked", async () => {
    render({ ...never, revoked_at: "2026-08-01T00:00:00Z" });
    expect(await screen.findByText(/You stopped this on/)).toBeInTheDocument();
    // And it is offered again rather than closed off.
    expect(screen.getByText("Let it read as me")).toBeInTheDocument();
  });

  it("says nothing about anybody else", async () => {
    render({ ...never, granted: true, can_read: true, can_write: true });
    await screen.findByText("Acting as you");
    expect(screen.queryByText(/member/i)).toBeNull();
  });
});
