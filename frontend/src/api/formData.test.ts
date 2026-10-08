import { describe, expect, it } from "vitest";

import { toFormData } from "./formData";

describe("toFormData", () => {
  it("repeats a list's field, keeps files, stringifies the rest and drops what is absent", () => {
    const image = new File(["x"], "a.png", { type: "image/png" });
    const form = toFormData({
      images: [image, image],
      title: "Shelf",
      version: 3,
      notes: null,
      listing_uid: undefined,
    });

    expect(form.getAll("images")).toHaveLength(2);
    expect((form.get("images") as File).name).toBe("a.png");
    expect(form.get("title")).toBe("Shelf");
    expect(form.get("version")).toBe("3");
    expect(form.has("notes")).toBe(false);
    expect(form.has("listing_uid")).toBe(false);
  });
});
