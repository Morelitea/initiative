/**
 * Where a sign-in goes. A browser, and a page a link opened for one server,
 * show the kind of server as a chip; signing in or up in the app picks one
 * inside the card and keeps the address it was given.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { getSelfHostedAddress, setSelfHostedAddress } from "@/lib/serverStorage";
import { freshAnswers, readStartDraft, saveStartDraft } from "@/lib/startFlow";

import { ServerChip, ServerPicker } from "./ServerChoice";

const mocks = vi.hoisted(() => ({ clearStart: vi.fn() }));

vi.mock("@/lib/startFlow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/startFlow")>();
  mocks.clearStart.mockImplementation(actual.clearStart);
  return { ...actual, clearStart: () => mocks.clearStart() };
});

describe("ServerChip", () => {
  it("shows the kind of server without letting it change", () => {
    renderWithProviders(<ServerChip />);

    expect(screen.getByText(/^self-hosted$/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

describe("ServerPicker", () => {
  it("shows a browser the chip, since it is on its server already", () => {
    renderWithProviders(<ServerPicker />, { server: { isNativePlatform: false } });

    expect(screen.getByText(/^self-hosted$/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("moves the app to another self-hosted server, signed out of the last", async () => {
    const user = userEvent.setup();
    setSelfHostedAddress("https://old.example.com");
    saveStartDraft(freshAnswers("personal"));
    const logout = vi.fn();
    const setServerUrl = vi.fn();
    const testServerConnection = vi.fn().mockResolvedValue({ valid: true });
    renderWithProviders(<ServerPicker />, {
      auth: { user: buildUser(), logout },
      server: {
        isNativePlatform: true,
        serverUrl: "https://old.example.com/api/v1",
        setServerUrl,
        testServerConnection,
      },
    });

    const address = screen.getByRole("textbox", { name: /server address/i });
    expect(address).toHaveValue("https://old.example.com");
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(testServerConnection).toHaveBeenCalledWith("https://new.example.com");
    expect(setServerUrl).toHaveBeenCalledWith("https://new.example.com");
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(
      setServerUrl.mock.invocationCallOrder[0]
    );
    expect(readStartDraft()).toBeNull();
    expect(getSelfHostedAddress()).toBe("https://new.example.com");
  });

  it("says the app is connected to the address it shows", () => {
    setSelfHostedAddress("https://home.example.com");
    renderWithProviders(<ServerPicker />, {
      server: { isNativePlatform: true, serverUrl: "https://home.example.com/api/v1" },
    });

    expect(screen.getByRole("button", { name: /^connected$/i })).toBeDisabled();
  });

  it("stays on the server, signed in, when the switch cannot finish", async () => {
    const user = userEvent.setup();
    mocks.clearStart.mockRejectedValueOnce(new Error("storage unavailable"));
    const logout = vi.fn();
    const setServerUrl = vi.fn();
    renderWithProviders(<ServerPicker />, {
      auth: { user: buildUser(), logout },
      server: {
        isNativePlatform: true,
        serverUrl: "https://old.example.com/api/v1",
        setServerUrl,
        testServerConnection: vi.fn().mockResolvedValue({ valid: true }),
      },
    });

    const address = screen.getByRole("textbox", { name: /server address/i });
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(await screen.findByText(/could not connect to server/i)).toBeInTheDocument();
    expect(logout).not.toHaveBeenCalled();
    expect(setServerUrl).not.toHaveBeenCalled();
  });
});
