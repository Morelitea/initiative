import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useCreateDocument, useTemplateAutocomplete } from "@/hooks/useDocuments";
import { toast } from "@/lib/chesterToast";

/** Sentinel for the "no template" option — the combobox needs a value. */
const BLANK_TEMPLATE = "blank";

interface CreateWikilinkDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Title of the document to create */
  title: string;
  /** Initiative ID where the document will be created */
  initiativeId: number;
  /** Whether the user has permission to create documents */
  canCreate: boolean;
  /** Called after successful creation with the new document ID */
  onCreated?: (documentId: number) => void;
}

export function CreateWikilinkDocumentDialog({
  open,
  onOpenChange,
  title,
  initiativeId,
  canCreate,
  onCreated,
}: CreateWikilinkDocumentDialogProps) {
  const { t } = useTranslation(["documents", "common"]);

  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  // Server search only returns matches for the live query, so the picker can't
  // look the selected template's title up from the current page — remember it.
  const [selectedTemplateLabel, setSelectedTemplateLabel] = useState<string | null>(null);
  const [templateSearch, setTemplateSearch] = useState("");

  // Guild-wide server typeahead over templates — bounded, and gated to what
  // this user can actually see by the same RLS/DAC rules as the document list.
  const templateDocumentsQuery = useTemplateAutocomplete(templateSearch, {
    enabled: open && canCreate,
  });

  const templateItems = useMemo(() => {
    const templates = (templateDocumentsQuery.data ?? []).map((doc) => ({
      value: String(doc.id),
      label: doc.title,
    }));
    // "Blank document" is the default choice, not a search result: offer it
    // only in the unsearched list, so a query matching no template leaves the
    // list genuinely empty and the picker can say so.
    return templateSearch
      ? templates
      : [{ value: BLANK_TEMPLATE, label: t("wikilink.blankDocument") }, ...templates];
  }, [templateDocumentsQuery.data, templateSearch, t]);

  // Reset template selection when dialog closes
  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setSelectedTemplateId("");
      setSelectedTemplateLabel(null);
    }
    onOpenChange(newOpen);
  };

  const createDocument = useCreateDocument({
    onSuccess: (document) => {
      toast.success(t("wikilink.created"));
      onOpenChange(false);
      onCreated?.(document.id);
    },
  });

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("wikilink.title")}</AlertDialogTitle>
          <AlertDialogDescription>
            {canCreate
              ? t("wikilink.descriptionCanCreate", { title })
              : t("wikilink.descriptionNoPermission", { title })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {canCreate && (
          <div className="space-y-2 py-2">
            <Label>{t("wikilink.templateLabel")}</Label>
            <AsyncCombobox
              items={templateItems}
              value={selectedTemplateId || null}
              selectedLabel={selectedTemplateLabel}
              onValueChange={(value) => {
                setSelectedTemplateId(value);
                setSelectedTemplateLabel(
                  templateItems.find((item) => item.value === value)?.label ?? null
                );
              }}
              onSearchChange={setTemplateSearch}
              loading={templateDocumentsQuery.isFetching}
              placeholder={t("wikilink.blankDocument")}
              searchPlaceholder={t("wikilink.searchTemplates")}
              emptyMessage={t("wikilink.noTemplates")}
              aria-label={t("wikilink.templateLabel")}
            />
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
          {canCreate && (
            <Button
              onClick={() =>
                createDocument.mutate({
                  title: title.trim(),
                  initiative_id: initiativeId,
                  template_id:
                    selectedTemplateId && selectedTemplateId !== BLANK_TEMPLATE
                      ? Number(selectedTemplateId)
                      : undefined,
                })
              }
              disabled={createDocument.isPending}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("wikilink.creating")}
                </>
              ) : (
                t("wikilink.createDocument")
              )}
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
