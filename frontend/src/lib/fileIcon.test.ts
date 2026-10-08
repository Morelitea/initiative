import { PenTool, ScrollText, Sheet } from "lucide-react";
import { describe, expect, it } from "vitest";

import { fileIcon } from "@/lib/fileIcon";

describe("fileIcon", () => {
  it("draws a spreadsheet as a sheet, not as prose", () => {
    // The relations card used to give every file the default scroll, which
    // said nothing about which of them was which.
    const { Icon, colorClass } = fileIcon({ file_type: "spreadsheet" });
    expect(Icon).toBe(Sheet);
    expect(colorClass).toBe("text-emerald-500");
  });

  it("draws a whiteboard as a pen", () => {
    expect(fileIcon({ file_type: "whiteboard" }).Icon).toBe(PenTool);
  });

  it("draws an ordinary file as a scroll", () => {
    expect(fileIcon({ file_type: "native" }).Icon).toBe(ScrollText);
  });

  it("draws a file by its format rather than by being a file", () => {
    const pdf = fileIcon({ file_type: "file", original_filename: "contract.pdf" });
    const image = fileIcon({ file_type: "file", mime_type: "image/png" });
    expect(pdf.Icon).not.toBe(ScrollText);
    expect(image.Icon).not.toBe(pdf.Icon);
  });

  it("uses a recognised provider's own mark for a smart link", () => {
    const figma = fileIcon({
      file_type: "smart_link",
      smart_link_url: "https://www.figma.com/file/abc",
    });
    expect(figma.Icon).not.toBe(ScrollText);
  });

  it("falls back rather than failing on a smart link with no url", () => {
    expect(fileIcon({ file_type: "smart_link" }).Icon).toBe(ScrollText);
  });

  it("survives a row that says nothing about itself", () => {
    expect(fileIcon({}).Icon).toBe(ScrollText);
  });
});
