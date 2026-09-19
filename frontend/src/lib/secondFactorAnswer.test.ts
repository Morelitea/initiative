import { describe, expect, it } from "vitest";

import { classifySecondFactorAnswer } from "./secondFactorAnswer";

describe("classifySecondFactorAnswer", () => {
  it("reads six bare digits as a live code", () => {
    expect(classifySecondFactorAnswer("123456")).toEqual({ code: "123456" });
  });

  it("reads a code the way an authenticator shows it", () => {
    // "123 456" is what the app displays and what gets pasted.
    expect(classifySecondFactorAnswer("123 456")).toEqual({ code: "123456" });
  });

  it("ignores surrounding whitespace", () => {
    expect(classifySecondFactorAnswer("  123456 ")).toEqual({ code: "123456" });
  });

  it("reads a recovery code as one, dashes and all", () => {
    expect(classifySecondFactorAnswer("abcde-fghij-klmno-p")).toEqual({
      recovery_code: "abcde-fghij-klmno-p",
    });
  });

  it("counts the digits with the dashes out", () => {
    // A recovery code is five-character groups, so six digits split by dashes
    // is not one: it is somebody typing a live code with separators.
    expect(classifySecondFactorAnswer("12-34-56")).toEqual({ code: "123456" });
  });

  it("keeps a recovery code's own case and dashes", () => {
    expect(classifySecondFactorAnswer(" 4phx6-mpc7t-7sptb-3 ")).toEqual({
      recovery_code: "4phx6-mpc7t-7sptb-3",
    });
  });
});
