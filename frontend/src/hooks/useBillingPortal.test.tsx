import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBillingPortal } from "./useBillingPortal";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing, isLoading: false }),
}));

vi.mock("@/api/generated/communities/communities", () => ({
  createCommunityBillingHandoff: vi.fn(async () => ({ handoff_token: "TOK" })),
}));

const environment = vi.hoisted(() => ({
  get: vi.fn(async (): Promise<{ installer?: string }> => ({})),
  storeCountry: vi.fn(async (): Promise<{ country?: string }> => ({})),
}));
vi.mock("@/plugins/appEnvironment", () => ({
  default: environment,
  PLAY_STORE_INSTALLER: "com.android.vending",
}));

const PORTAL = "https://billing.example.com";
const onPlatform = (platform: string) =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

beforeEach(() => {
  state.billing = { url: PORTAL };
  environment.get.mockResolvedValue({});
  environment.storeCountry.mockResolvedValue({});
});

const canSellOn = async () => {
  const { result } = renderHook(() => useBillingPortal());
  // Let a phone's store answer before reading.
  await act(async () => {});
  return result;
};

describe("useBillingPortal canSell", () => {
  it("sells on the web and the desktop app where a portal is configured", async () => {
    expect((await canSellOn()).current.canSell).toBe(true);
    onPlatform("electron");
    expect((await canSellOn()).current.canSell).toBe(true);
  });

  it("never sells without a portal", async () => {
    state.billing = null;
    expect((await canSellOn()).current.canSell).toBe(false);
  });

  it("sells on iOS on the US storefront only", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "USA" });
    const result = await canSellOn();
    await waitFor(() => expect(result.current.canSell).toBe(true));
  });

  it("does not sell on iOS elsewhere", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "CAN" });
    const result = await canSellOn();
    expect(result.current.canSell).toBe(false);
    expect(result.current.reserveTab()).toBeNull();
  });

  it("sells on a Play install in an allowed country, and not in another", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "com.android.vending" });
    environment.storeCountry.mockResolvedValue({ country: "NL" });
    const allowed = await canSellOn();
    await waitFor(() => expect(allowed.current.canSell).toBe(true));
  });

  it("does not sell on a Play install outside the allowed countries", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "com.android.vending" });
    environment.storeCountry.mockResolvedValue({ country: "IN" });
    expect((await canSellOn()).current.canSell).toBe(false);
  });

  it("sells on an Android install from outside Play", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "dev.imranr.obtainium" });
    const result = await canSellOn();
    await waitFor(() => expect(result.current.canSell).toBe(true));
  });
});

describe("useBillingPortal openPortal", () => {
  it("opens the portal in the browser sheet on a phone that may sell", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "USA" });
    const open = vi.spyOn(window, "open");
    const result = await canSellOn();
    await waitFor(() => expect(result.current.canSell).toBe(true));

    expect(result.current.reserveTab()).toBeNull();
    await act(() => result.current.openPortal(42, "upgrade"));

    expect(Browser.open).toHaveBeenCalledWith({
      url: `${PORTAL}/upgrade?community=42&lang=en#handoff=TOK`,
    });
    expect(open).not.toHaveBeenCalled();
  });

  it("opens a tab on the web, not the browser sheet", async () => {
    const tab = { location: { href: "" }, opener: {} } as unknown as Window;
    const open = vi.spyOn(window, "open").mockReturnValue(tab);
    const result = await canSellOn();

    await act(() => result.current.openPortal(42, "manage"));

    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(tab.location.href).toBe(`${PORTAL}/manage?community=42&lang=en#handoff=TOK`);
    expect(Browser.open).not.toHaveBeenCalled();
  });

  it("opens nothing on a phone that may not sell", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "com.android.vending" });
    const open = vi.spyOn(window, "open");
    const result = await canSellOn();

    await act(() => result.current.openPortal(42, "upgrade"));

    expect(Browser.open).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });
});
