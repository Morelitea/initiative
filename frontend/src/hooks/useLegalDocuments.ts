/**
 * A deployment's own terms and privacy policy.
 *
 * The documents are not in this repository — a deployment that has terms of
 * its own serves them from the external portal it names, and the app reads
 * them through `/api/v1/legal`, the server's window onto it. Going through
 * the server rather than straight there is what makes them readable from the
 * native build, whose origin is not an `https://` one, and it means the
 * revision a reader is shown is the revision the server records against their
 * acceptance.
 *
 * Nothing is asked of a deployment that names no portal
 * (`useAppConfig().billing` is null): it has no terms of its own, and every
 * route here answers 404.
 */

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import type { LegalIndexRead } from "@/api/generated/initiativeAPI.schemas";
import { useAppConfig } from "@/hooks/useAppConfig";

/** The two slugs an account cannot exist here without accepting. The server
 *  sends its own list on the index; this is what the signup notice names
 *  before the index has loaded, and it is the same pair. */
export const REQUIRED_DOCUMENTS = ["terms", "privacy"] as const;

export type RequiredDocument = (typeof REQUIRED_DOCUMENTS)[number];

/** Where a reader goes to read one. */
export const legalDocumentPath = (slug: string) => `/legal/${slug}`;

/** Revisions are rare and the server caches its own read of them, so this is
 *  about not re-asking within a session rather than about freshness. */
const LEGAL_STALE_MS = 10 * 60 * 1000;

export const useLegalIndex = () => {
  const { billing } = useAppConfig();
  const enabled = Boolean(billing);
  const query = useQuery<LegalIndexRead>({
    queryKey: ["legal", "index"],
    queryFn: async () => (await apiClient.get<LegalIndexRead>("/legal")).data,
    enabled,
    staleTime: LEGAL_STALE_MS,
    retry: false,
  });

  return {
    /** Whether this deployment has terms at all. */
    enabled,
    documents: query.data?.documents ?? [],
    /** What the server says must be accepted, falling back to the pair the
     *  notice names while the index is still loading or unreachable. */
    required: query.data?.required ?? [...REQUIRED_DOCUMENTS],
    isLoading: query.isLoading,
  };
};

/** One document's markdown, straight from the server's proxy.
 *
 *  Held for the session rather than re-fetched on every mount: the bytes are
 *  long and unchanging, and the server revalidates against the portal on a
 *  content hash anyway. */
export const useLegalDocument = (slug: string | undefined) =>
  useQuery<string>({
    queryKey: ["legal", "document", slug ?? null],
    queryFn: async () =>
      (
        await apiClient.get<string>(`/legal/${slug}`, {
          responseType: "text",
          headers: { Accept: "text/markdown" },
        })
      ).data,
    enabled: Boolean(slug),
    staleTime: LEGAL_STALE_MS,
    retry: false,
  });
