import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";

const Harness = () => {
  const { ask, dialog } = useScopePrompt();
  const [picked, setPicked] = useState<string>("none");
  return (
    <>
      <button type="button" onClick={async () => setPicked(String(await ask("delete")))}>
        delete
      </button>
      <button
        type="button"
        onClick={async () =>
          setPicked(
            String(await ask("edit", { tool: "tasks", count: 4, scopes: ["this", "following"] }))
          )
        }
      >
        move task
      </button>
      <output>{picked}</output>
      {dialog}
    </>
  );
};

describe("useScopePrompt", () => {
  it("answers with the scope picked, or null when closed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "delete" }));
    await user.click(await screen.findByLabelText(/all events in the series/i));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(await screen.findByText("all")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "delete" }));
    await user.click(await screen.findByRole("button", { name: /cancel/i }));
    expect(await screen.findByText("null")).toBeInTheDocument();
  });

  it("asks in a task's words, with only the choices given", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "move task" }));
    expect(await screen.findByLabelText(/just this task/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/all tasks/i)).not.toBeInTheDocument();
    await user.click(screen.getByLabelText(/tasks after this point/i));
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByText("following")).toBeInTheDocument();
  });
});
