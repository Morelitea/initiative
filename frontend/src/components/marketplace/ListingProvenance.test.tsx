/**
 * "Who wrote this?", answered before installing.
 *
 * The load-bearing property is that the author's name is never shown on its
 * own. Three listings can claim the same name and mean three different things,
 * so each source gets its own sentence — and an operator-added listing claiming
 * a first-party name still says where it actually came from.
 *
 * The second half is the author's own address, which is a claim that arrived in
 * a manifest. Only an `https:` one is offered as a link; anything else is text.
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

  it("says a registry vouched for a registry listing", () => {
    renderWithProviders(<ListingProvenance listing={listing({ source: "registry" })} />);
    expect(screen.getByText("by Acme Widgets · verified")).toBeInTheDocument();
  });

  it("names the administrator for an operator listing", () => {
    renderWithProviders(<ListingProvenance listing={listing({ source: "operator" })} />);
    expect(screen.getByText("by Acme Widgets · added by your administrator")).toBeInTheDocument();
  });

  it("does not let a claimed name pass for a provenance", () => {
    // The reason the two are always shown together: an operator-uploaded
    // listing may call itself anything, and reads as what it actually is.
    renderWithProviders(
      <ListingProvenance listing={listing({ source: "operator", author_name: "Initiative" })} />
    );
    expect(screen.getByText("by Initiative · added by your administrator")).toBeInTheDocument();
    expect(screen.queryByText("by Initiative")).toBeNull();
  });

  it("states the claim and nothing more for a source it does not know", () => {
    // A source this build has no sentence for gets no trust story attached to
    // it — the name is repeated as claimed and left there.
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
    expect(screen.getByText("by Acme Widgets · verified")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("https://acme.example")).toBeNull();
  });
});
