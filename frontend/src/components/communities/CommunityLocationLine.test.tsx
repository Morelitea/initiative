import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CommunityLocation } from "@/lib/communityLocation";

import { CommunityLocationLine } from "./CommunityLocationLine";

const queenAnne: CommunityLocation = {
  text: "Seattle, Washington, United States",
  label: "Queen Anne Neighborhood",
  country: "US",
  latitude: 47.6,
  longitude: -122.3,
};

describe("CommunityLocationLine", () => {
  it("names the place after the community's own name for it, and opens it on a map", () => {
    render(<CommunityLocationLine location={queenAnne} />);

    expect(
      screen.getByRole("link", {
        name: "Location: Queen Anne Neighborhood, Seattle, Washington, United States",
      })
    ).toHaveAttribute("href", expect.stringContaining("openstreetmap.org/?mlat=47.6"));
  });

  it("is a plain line where it sits inside something clickable", () => {
    render(
      <CommunityLocationLine
        interactive={false}
        location={{ ...queenAnne, label: null, text: "Lyon, France" }}
      />
    );

    expect(screen.getByText("Lyon, France")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
