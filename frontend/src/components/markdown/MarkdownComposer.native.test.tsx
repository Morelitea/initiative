/**
 * On the native app a picture control offers the camera first — the composer's
 * picture button included — rather than only a file dialog.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MarkdownComposer } from "./MarkdownComposer";

const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

vi.mock("@/lib/nativeCamera", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/nativeCamera")>()),
  canCapturePhoto: () => true,
  capturePhoto: vi.fn(() => Promise.resolve(photo)),
}));

const Host = ({ upload }: { upload: (file: File) => Promise<string> }) => {
  const [value, setValue] = useState("");
  return <MarkdownComposer value={value} onChange={setValue} onUploadImage={upload} />;
};

describe("the picture button on the app", () => {
  it("offers the camera and the library, and puts the photo in", async () => {
    const user = userEvent.setup();
    const upload = vi.fn(() => Promise.resolve("/uploads/9/pasted-p.jpg"));
    renderWithProviders(<Host upload={upload} />);

    await user.click(screen.getByRole("button", { name: "Image" }));
    expect(await screen.findByRole("menuitem", { name: "Choose from library" })).toBeVisible();
    await user.click(screen.getByRole("menuitem", { name: "Take a photo" }));

    await waitFor(() => expect(upload).toHaveBeenCalledWith(photo));
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue("![photo](/uploads/9/pasted-p.jpg)")
    );
  });
});
