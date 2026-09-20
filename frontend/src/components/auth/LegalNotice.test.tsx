/**
 * The notice above the Create account button.
 *
 * Two things carry the weight. It must not appear on a deployment that has no
 * terms — a self-hoster being told they agree to somebody else's would be
 * plainly wrong — and where it does appear it has to name both documents and
 * let them be read, because pressing the button is the agreement and an
 * agreement you cannot read first is not one.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const useLegalIndex = vi.fn();

vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => useLegalIndex(),
}));

import { LegalNotice } from "@/components/auth/LegalNotice";

const hosted = (documents: { slug: string; title: string }[] = []) => {
  useLegalIndex.mockReturnValue({
    enabled: true,
    documents,
    required: ["terms", "privacy"],
    isLoading: false,
  });
};

describe("LegalNotice", () => {
  it("says nothing on a deployment with no terms of its own", () => {
    useLegalIndex.mockReturnValue({
      enabled: false,
      documents: [],
      required: ["terms", "privacy"],
      isLoading: false,
    });

    const { container } = renderWithProviders(<LegalNotice />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names both documents and links each one", () => {
    hosted([
      { slug: "terms", title: "Terms of Service" },
      { slug: "privacy", title: "Privacy Policy" },
    ]);

    renderWithProviders(<LegalNotice />);

    const terms = screen.getByRole("link", { name: "Terms of Service" });
    const privacy = screen.getByRole("link", { name: "Privacy Policy" });
    expect(terms).toHaveAttribute("href", "/legal/terms");
    expect(privacy).toHaveAttribute("href", "/legal/privacy");
    // Beside the form rather than instead of it: reading one must not lose
    // what somebody has already typed.
    expect(terms).toHaveAttribute("target", "_blank");
    expect(privacy).toHaveAttribute("target", "_blank");
  });

  it("reads correctly before the index has loaded", () => {
    // The titles arrive a moment after the form does. The notice ships with
    // the two names so it appears with the button rather than after it.
    hosted([]);

    renderWithProviders(<LegalNotice />);

    expect(screen.getByRole("link", { name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByText(/by creating an account you agree/i)).toBeInTheDocument();
  });

  it("uses the titles the portal publishes once it has them", () => {
    hosted([
      { slug: "terms", title: "Customer Agreement" },
      { slug: "privacy", title: "Privacy Notice" },
    ]);

    renderWithProviders(<LegalNotice />);

    expect(screen.getByRole("link", { name: "Customer Agreement" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Terms of Service" })).not.toBeInTheDocument();
  });
});
