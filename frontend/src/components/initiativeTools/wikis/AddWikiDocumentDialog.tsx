import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { DocumentType, Tool, type WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useAddWikiDocument } from "@/hooks/useWikis";
import { toast } from "@/lib/chesterToast";
import { TOOL_ICONS } from "@/lib/tools";

const DocumentIcon = TOOL_ICONS[Tool.document];

interface AddWikiDocumentDialogProps {
  wikiId: number;
  initiativeId: number;
  /** What the wiki already holds, so it is not offered twice. */
  pages: WikiPageSummary[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Put a document that already exists into this wiki.
 *
 * Only documents of the same initiative are offered: a wiki is an initiative's,
 * and reaching across one is a sharing decision rather than a filing one.
 *
 * Nothing is copied. The document keeps its address and its sharing, and this
 * only records that it belongs here too.
 *
 * Only WRITTEN documents are offered. A wiki draws a page it has borrowed with
 * the same editor it draws its own, so a spreadsheet or a whiteboard put in
 * one would be opened as prose it is not — and it is better not to be offered
 * a thing than to be handed it broken.
 */
export const AddWikiDocumentDialog = ({
  wikiId,
  initiativeId,
  pages,
  open,
  onOpenChange,
}: AddWikiDocumentDialogProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const [query, setQuery] = useState("");
  const add = useAddWikiDocument(wikiId);

  const documentsQuery = useDocumentsList(
    { initiative_id: initiativeId, document_type: DocumentType.native, page_size: 0 },
    { enabled: open }
  );

  const already = useMemo(
    () => new Set(pages.filter((page) => page.kind === "document").map((page) => page.id)),
    [pages]
  );

  const needle = query.trim().toLowerCase();
  const candidates = (documentsQuery.data?.items ?? [])
    .filter((document) => !already.has(document.id))
    .filter((document) => !needle || document.name.toLowerCase().includes(needle));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-5 py-4">
          <DialogTitle>{t("documents.addDocument")}</DialogTitle>
          <DialogDescription>{t("documents.pick")}</DialogDescription>
        </DialogHeader>

        <div className="border-b px-5 py-3">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("filters.searchLabel")}
            aria-label={t("documents.pick")}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {candidates.length === 0 ? (
            <p className="px-3 py-2 text-muted-foreground text-sm">{t("documents.none")}</p>
          ) : (
            <ul className="space-y-0.5">
              {candidates.map((document) => (
                <li key={document.id}>
                  <Button
                    variant="ghost"
                    className="h-auto w-full justify-start gap-2 px-3 py-2 text-left"
                    disabled={add.isPending}
                    onClick={() =>
                      add.mutate(document.id, {
                        onSuccess: () => {
                          toast.success(t("documents.added"));
                          onOpenChange(false);
                        },
                      })
                    }
                  >
                    <DocumentIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{document.name}</span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
