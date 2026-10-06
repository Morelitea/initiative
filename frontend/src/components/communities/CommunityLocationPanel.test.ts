import { describe, expect, it } from "vitest";

import { type Draft, withPlace } from "./CommunityLocationPanel";

const seattle: Draft = {
  country: "US",
  region: "Washington",
  region_code: "WA",
  city: "Seattle",
  address: "1 Queen Anne Ave N",
  postal_code: "98109",
  label: "Queen Anne Neighborhood",
};

describe("withPlace", () => {
  it("keeps the street and name while the country stays", () => {
    const next = withPlace(seattle, {
      country: "US",
      region: "Washington",
      region_code: "WA",
      city: "Tacoma",
    });

    expect(next).toMatchObject({
      city: "Tacoma",
      address: "1 Queen Anne Ave N",
      label: "Queen Anne Neighborhood",
    });
  });

  it("clears the street, postcode and name with a new country", () => {
    const next = withPlace(seattle, { country: "JP", region: "", region_code: "", city: "" });

    expect(next).toEqual({
      country: "JP",
      region: "",
      region_code: "",
      city: "",
      address: "",
      postal_code: "",
      label: "",
    });
  });
});
