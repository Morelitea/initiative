/**
 * Where a sign-in goes, under every signed-out card. A browser, and a page a
 * link opened for one server, show the kind of server; signing in or up in
 * the app picks one and keeps the address it was given.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { getSelfHostedAddress, setSelfHostedAddress } from "@/lib/serverStorage";

import { ServerChoice } from "./ServerChoice";

describe("ServerChoice", () => {
  it.each([
    ["a browser, even where it signs in", false, true],
    ["the app, where it does not sign in", true, false],
  ])("shows %s its server without letting it change", (_, isNativePlatform, pick) => {
    renderWithProviders(<ServerChoice pick={pick} />, { server: { isNativePlatform } });

    const server = screen.getByRole("combobox", { name: /^server$/i });
    expect(server).toBeDisabled();
    expect(server).toHaveTextContent(/self-hosted/i);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("connects the app to a self-hosted address and keeps it", async () => {
    const user = userEvent.setup();
    setSelfHostedAddress("https://old.example.com");
    const setServerUrl = vi.fn();
    const testServerConnection = vi.fn().mockResolvedValue({ valid: true });
    renderWithProviders(<ServerChoice pick />, {
      server: { isNativePlatform: true, serverUrl: null, setServerUrl, testServerConnection },
    });

    const address = screen.getByRole("textbox", { name: /server address/i });
    expect(address).toHaveValue("https://old.example.com");
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(testServerConnection).toHaveBeenCalledWith("https://new.example.com");
    expect(setServerUrl).toHaveBeenCalledWith("https://new.example.com");
    expect(getSelfHostedAddress()).toBe("https://new.example.com");
  });

  it("says the app is connected to the address it shows", () => {
    setSelfHostedAddress("https://home.example.com");
    renderWithProviders(<ServerChoice pick />, {
      server: { isNativePlatform: true, serverUrl: "https://home.example.com/api/v1" },
    });

    expect(screen.getByRole("button", { name: /^connected$/i })).toBeDisabled();
  });
});
