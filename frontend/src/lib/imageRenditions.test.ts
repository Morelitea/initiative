import { describe, expect, it } from "vitest";

import {
  GUILD_BANNER_CARD,
  GUILD_BANNER_FULL,
  GUILD_ICON,
  ImageRenditionError,
  MAX_SOURCE_BYTES,
  renderGuildIcon,
} from "./imageRenditions";

const file = (bytes: number, type: string) =>
  new File([new Uint8Array(bytes)], "pick.bin", { type });

describe("guild image specs", () => {
  it("keeps the icon square and the banner renditions at 4:1", () => {
    expect(GUILD_ICON.width / GUILD_ICON.height).toBe(1);
    expect(GUILD_BANNER_CARD.width / GUILD_BANNER_CARD.height).toBe(4);
    expect(GUILD_BANNER_FULL.width / GUILD_BANNER_FULL.height).toBe(4);
  });

  it("keeps the card rendition far lighter than the one it is a thumbnail of", () => {
    // A directory page is up to sixty cards; that is the whole reason the card
    // rendition exists.
    expect(GUILD_BANNER_CARD.maxBytes).toBeLessThan(GUILD_BANNER_FULL.maxBytes / 4);
  });
});

describe("renderGuildIcon", () => {
  it("refuses a file that is not an image before reading any of it", async () => {
    await expect(renderGuildIcon(file(16, "application/pdf"))).rejects.toThrow(ImageRenditionError);
    await expect(renderGuildIcon(file(16, "application/pdf"))).rejects.toMatchObject({
      code: "notAnImage",
    });
  });

  it("refuses a source too large to work with, before decoding it", async () => {
    await expect(renderGuildIcon(file(MAX_SOURCE_BYTES + 1, "image/png"))).rejects.toMatchObject({
      code: "tooLarge",
    });
  });
});
