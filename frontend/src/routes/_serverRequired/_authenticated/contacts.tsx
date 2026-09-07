import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * My Contacts, which My Messages replaced.
 *
 * The page is gone, the address is not. It only shipped in 0.65.0, so there is
 * not much of it about — but it was a navigation item in a release, which is
 * enough for a bookmark and a link in somebody's chat, and a redirect is one
 * file. Everything it did happens on My Messages now: the people you can
 * reach, the requests either way round, and the picker that finds somebody you
 * have never messaged. So that is where a stale link lands, rather than on
 * nothing.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/contacts")({
  beforeLoad: () => {
    throw redirect({ to: "/messages", replace: true });
  },
});
