import { screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";

const failed = (status: number): AxiosError => {
  const error = new AxiosError("failed");
  error.response = {
    status,
    statusText: "",
    data: {},
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

describe("ToolAccessStatus", () => {
  it.each([
    ["no access on a 403", failed(403), "Access Denied"],
    ["not found on a 404", failed(404), "Queue not found"],
    ["not found when there was nothing to read", null, "Queue not found"],
    ["the failure itself otherwise", failed(500), "Something went wrong. Please try again."],
  ])("says %s", async (_, error, title) => {
    renderPage(() => (
      <ToolAccessStatus error={error} keys="queues:" backTo="/" backLabel="Back to Queues" />
    ));

    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Queues" })).toBeInTheDocument();
  });
});
