import { useNavigate } from "@tanstack/react-router";
import { Check, FileStack, Home, MoreHorizontal, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageRead, WikiRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDeleteWikiPage, useUpdateWiki } from "@/hooks/useWikis";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

interface WikiPageActionsProps {
  wiki: WikiRead;
  page: WikiPageRead;
  canWrite: boolean;
  initiativeId: number;
}

/**
 * What can be done to this page, as opposed to the wiki.
 *
 * Kept behind one control beside the title: a wiki is read far more than it is
 * rearranged, so the three things that change a page's standing should not be
 * three buttons in the way of the words.
 */
export const WikiPageActions = ({ wiki, page, canWrite, initiativeId }: WikiPageActionsProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useGuildPath();
  const navigate = useNavigate();
  const updateWiki = useUpdateWiki(wiki.id);
  const deletePage = useDeleteWikiPage(wiki.id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!canWrite) {
    return null;
  }

  const isHome = wiki.home_page_id === page.id;
  const isTemplate = wiki.template_page_id === page.id;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="mt-2 size-8 shrink-0"
            aria-label={t("page.actions")}
          >
            <MoreHorizontal className="size-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuItem
            onSelect={() => {
              updateWiki.mutate(
                { home_page_id: page.id },
                { onSuccess: () => toast.success(t("pages.homeSet")) }
              );
            }}
            disabled={isHome}
          >
            {isHome ? (
              <Check className="size-4" aria-hidden />
            ) : (
              <Home className="size-4" aria-hidden />
            )}
            {isHome ? t("pages.isHome") : t("page.setHome")}
          </DropdownMenuItem>

          <DropdownMenuItem
            onSelect={() => {
              updateWiki.mutate(
                { template_page_id: page.id },
                { onSuccess: () => toast.success(t("settings.saved")) }
              );
            }}
            disabled={isTemplate}
          >
            {isTemplate ? (
              <Check className="size-4" aria-hidden />
            ) : (
              <FileStack className="size-4" aria-hidden />
            )}
            {isTemplate ? t("page.isTemplate") : t("page.useAsTemplate")}
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          <DropdownMenuItem
            className="text-destructive hover:text-destructive"
            onSelect={() => setConfirmingDelete(true)}
          >
            <Trash2 className="size-4" aria-hidden />
            {t("page.delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("pages.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("pages.deleteDescription")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                deletePage.mutate(page.id, {
                  onSuccess: () => {
                    toast.success(t("pages.deleted"));
                    void navigate({
                      to: gp(toolDetailRoute(Tool.wiki, initiativeId, wiki.id)),
                    });
                  },
                })
              }
            >
              {t("page.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};
