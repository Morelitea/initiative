import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { discardPastedImage, uploadPastedImage } from "@/lib/attachmentUtils";

import { usePastedImages } from "./usePastedImages";

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 9 }));
vi.mock("@/lib/attachmentUtils", () => ({
  uploadPastedImage: vi.fn(),
  discardPastedImage: vi.fn(() => Promise.resolve()),
}));

const png = (name: string) => new File(["x"], name, { type: "image/png" });

afterEach(() => vi.clearAllMocks());

describe("pasted pictures", () => {
  it("are offered back to the server when the page is left", async () => {
    vi.mocked(uploadPastedImage)
      .mockResolvedValueOnce("/uploads/9/pasted-a.png")
      .mockResolvedValueOnce("/uploads/9/pasted-b.png");
    const { result, unmount } = renderHook(() => usePastedImages());

    await act(async () => {
      await result.current(png("a.png"));
      await result.current(png("b.png"));
    });
    expect(discardPastedImage).not.toHaveBeenCalled();

    unmount();

    // Every one is asked about; the server keeps the ones a save kept.
    expect(discardPastedImage).toHaveBeenCalledWith(9, "/uploads/9/pasted-a.png");
    expect(discardPastedImage).toHaveBeenCalledWith(9, "/uploads/9/pasted-b.png");
  });

  it("asks about nothing when nothing was pasted", () => {
    const { unmount } = renderHook(() => usePastedImages());

    unmount();

    expect(discardPastedImage).not.toHaveBeenCalled();
  });

  it("does not remember a picture that failed to store", async () => {
    vi.mocked(uploadPastedImage).mockRejectedValueOnce(new Error("full"));
    const { result, unmount } = renderHook(() => usePastedImages());

    await act(async () => {
      await expect(result.current(png("a.png"))).rejects.toThrow("full");
    });
    unmount();

    expect(discardPastedImage).not.toHaveBeenCalled();
  });
});
