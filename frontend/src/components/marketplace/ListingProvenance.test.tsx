/**
 * "Who wrote this?", answered before installing.
 *
 * Authorship, not approval: every listing on a deployment is there because an
 * administrator put it there, so where a listing arrived from is not a ranking
 * the reader needs — and rendering one would suggest some apps got in without
 * the administrator, which is not a state this platform has.
 *
 * What is left is the name, with listings shipped in this build named as ours,
 * and the author's own address — a claim that arrived in a manifest, so only an
 * `https:` one is offered as a link and anything else is text.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildMarketplaceListing } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { MarketplaceListingSummary } from "@/api/generated/initiativeAPI.schemas";

import { ListingProvenance } from "./ListingProvenance";

const listing = (overrides: Partial<MarketplaceListingSummary> = {}) =>
  buildMarketplaceListing({ author_name: "Acme Widgets", ...overrides });

describe("ListingProvenance", () => {
  it("credits this build for a listing that ships with it", () => {
    renderWithProviders(
      <ListingProvenance listing={listing({ source: "builtin", author_name: "Initiative" })} />
    );
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("names the author of a registry listing", () => {
    renderWithProviders(<ListingProvenance listing={listing({ source: "registry" })} />);
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("names the author of an operator listing the same way", () => {
    // Same sentence for both, deliberately: an administrator chose the registry
    // and dropped in the file, so neither is more theirs than the other.
    renderWithProviders(<ListingProvenance listing={listing({ source: "operator" })} />);
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("states the claim for a source it does not know", () => {
    renderWithProviders(
      <ListingProvenance listing={{ source: "something-new", author_name: "Acme Widgets" }} />
    );
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("opens an https author link as untrusted third-party content", () => {
    renderWithProviders(
      <ListingProvenance
        listing={listing({ source: "registry", author_url: "https://acme.example/team" })}
      />
    );
    const link = screen.getByRole("link", { name: "Author's website" });
    expect(link).toHaveAttribute("href", "https://acme.example/team");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
  });

  it("will not hand a click to a plain http address", () => {
    // Shown, because it is part of what the listing claims; not clickable,
    // because only https is offered as a link.
    renderWithProviders(
      <ListingProvenance
        listing={listing({ source: "operator", author_url: "http://acme.example" })}
      />
    );
    expect(screen.getByText("http://acme.example")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("will not hand a click to a script url", () => {
    renderWithProviders(
      <ListingProvenance
        listing={listing({ source: "operator", author_url: "javascript:alert(1)" })}
      />
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("leaves the author's address off where there is no room for it", () => {
    renderWithProviders(
      <ListingProvenance
        listing={listing({ source: "registry", author_url: "https://acme.example" })}
        showAuthorUrl={false}
      />
    );
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("https://acme.example")).toBeNull();
  });
});
