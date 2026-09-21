import { Trans, useTranslation } from "react-i18next";

import { legalDocumentPath, useLegalIndex } from "@/hooks/useLegalDocuments";

/** A link to one document, opened beside whatever the reader was doing.
 *
 *  A plain anchor rather than a router link: it opens in its own tab, so the
 *  form somebody is halfway through filling in is still there when they come
 *  back, and nothing about reading a policy belongs to the signup route. */
export const DocumentLink = ({ slug, children }: { slug: string; children?: React.ReactNode }) => (
  <a
    href={legalDocumentPath(slug)}
    target="_blank"
    rel="noreferrer"
    className="text-primary underline-offset-4 hover:underline"
  >
    {children}
  </a>
);

/** The portal's own title for a document, or the name it ships with until the
 *  index has loaded — so the notice never appears late or changes shape. */
const useDocumentTitle = () => {
  const { documents } = useLegalIndex();
  return (slug: string, fallback: string) =>
    documents.find((document) => document.slug === slug)?.title ?? fallback;
};

/**
 * The line under the Create account button, where there are terms to agree
 * to.
 *
 * Pressing the button is the agreement — there is no box to tick, which is
 * both what every comparable product does and what the terms themselves
 * contemplate. The notice has to sit above the act it describes for that to
 * be true, so it renders immediately before the button rather than in the
 * card footer.
 *
 * Renders nothing at all where the deployment has no terms of its own.
 */
export const LegalNotice = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { enabled } = useLegalIndex();
  const title = useDocumentTitle();

  if (!enabled) {
    return null;
  }

  return (
    <p className="text-muted-foreground text-xs">
      <Trans
        t={t}
        i18nKey="legal:signupNotice"
        values={{
          appName: t("common:appName"),
          terms: title("terms", t("legal:termsTitle")),
          privacy: title("privacy", t("legal:privacyTitle")),
        }}
        components={{
          termsLink: <DocumentLink slug="terms" />,
          privacyLink: <DocumentLink slug="privacy" />,
        }}
      />
    </p>
  );
};

/** The same two links, without the sentence around them. */
export const LegalDocumentLinks = () => {
  const { t } = useTranslation("legal");
  const title = useDocumentTitle();

  return (
    <div className="flex flex-wrap gap-4 text-sm">
      <DocumentLink slug="terms">{title("terms", t("termsTitle"))}</DocumentLink>
      <DocumentLink slug="privacy">{title("privacy", t("privacyTitle"))}</DocumentLink>
    </div>
  );
};
