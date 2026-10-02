/**
 * The app's first screen: where the person's Initiative runs.
 *
 * Initiative Cloud is listed but closed until it opens, so the only road is a
 * self-hosted server's address.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { ConnectServerPage } from "./ConnectServerPage";

describe("ConnectServerPage", () => {
  it("connects to a self-hosted server while the cloud is closed", async () => {
    const user = userEvent.setup();
    const setServerUrl = vi.fn();
    const testServerConnection = vi.fn().mockResolvedValue({ valid: true });

    renderPage(ConnectServerPage, {
      initialRoute: "/connect",
      server: { setServerUrl, testServerConnection },
    });

    expect(await screen.findByRole("radio", { name: /initiative cloud/i })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /self-hosted/i })).toBeChecked();

    await user.type(screen.getByLabelText(/server url/i), "https://initiative.example.com");
    await user.click(screen.getByRole("button", { name: /connect/i }));

    expect(testServerConnection).toHaveBeenCalledWith("https://initiative.example.com");
    expect(setServerUrl).toHaveBeenCalledWith("https://initiative.example.com");
  });
});
