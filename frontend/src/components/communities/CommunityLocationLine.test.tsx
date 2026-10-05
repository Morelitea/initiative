import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CommunityLocation } from "@/lib/communityLocation";

import { CommunityLocationLine } from "./CommunityLocationLine";

const at = (parts: Partial<CommunityLocation> & { country: string }): CommunityLocation => ({
  region: null,
  region_code: null,
  city: null,
  address: null,
  postal_code: null,
  label: null,
  ...parts,
});

describe("CommunityLocationLine", () => {
  it("is plain text when the line says everything", () => {
    render(<CommunityLocationLine location={at({ country: "FR", city: "Lyon" })} />);

    expect(screen.getByText("Lyon, France")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the street off the row and shows it on request", async () => {
    const user = userEvent.setup();
    render(
      <CommunityLocationLine
        location={at({
          country: "US",
          region: "Washington",
          region_code: "WA",
          city: "Seattle",
          address: "1 Queen Anne Ave N",
          postal_code: "98109",
          label: "Queen Anne Neighborhood",
        })}
      />
    );

    expect(
      screen.getByRole("button", { name: "Location: Queen Anne Neighborhood, Seattle, WA" })
    ).toBeInTheDocument();
    expect(screen.queryByText("1 Queen Anne Ave N")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button"));

    expect(await screen.findByText("1 Queen Anne Ave N")).toBeInTheDocument();
    expect(screen.getByText("Seattle, Washington 98109")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("openstreetmap.org/search")
    );
  });
});
