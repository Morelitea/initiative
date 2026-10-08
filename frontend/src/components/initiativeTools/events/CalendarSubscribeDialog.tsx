import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateApiKey, useMyApiKeys } from "@/hooks/useSecurity";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { buildApiUrl } from "@/lib/wsUrl";

/** The longest name an API key takes. */
const KEY_NAME_MAX = 100;

type CalendarSubscribeDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  communityId: number;
  calendar: { id: number; name: string };
};

/**
 * A subscription link to one calendar, for another calendar app.
 *
 * The link is a personal API key that names this calendar, so it follows the
 * community's API-access setting, shows under Settings › Security, and is
 * shown once. Getting another replaces it.
 */
export const CalendarSubscribeDialog = ({
  open,
  onOpenChange,
  communityId,
  calendar,
}: CalendarSubscribeDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const [link, setLink] = useState<string | null>(null);
  const keysQuery = useMyApiKeys();
  const hasLink = (keysQuery.data?.keys ?? []).some(
    (key) =>
      key.resource_type === Tool.calendar &&
      key.resource_id === calendar.id &&
      key.community_id === communityId
  );

  const createLink = useCreateApiKey({
    onSuccess: (data) => {
      const url = buildApiUrl(`c/${communityId}/calendars/${calendar.id}/feed.ics`);
      url.searchParams.set("token", data.secret);
      setLink(url.toString());
    },
    onError: (error) => toast.error(getErrorMessage(error, "calendars:subscribe.error")),
  });

  const close = () => {
    onOpenChange(false);
    setLink(null);
  };

  const copyLink = () => {
    if (!link || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(link).then(() => {
      toast.success(t("subscribe.copied"));
    });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("subscribe.title", { name: calendar.name })}</DialogTitle>
          <DialogDescription>{t("subscribe.description")}</DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">{t("subscribe.secret")}</p>
        {link ? (
          <>
            <code className="block break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm">
              {link}
            </code>
            <p className="text-muted-foreground text-sm">{t("subscribe.manage")}</p>
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={copyLink}>
                {t("subscribe.copy")}
              </Button>
              <Button type="button" variant="outline" asChild>
                <a href={link.replace(/^https?:/, "webcal:")}>{t("subscribe.open")}</a>
              </Button>
              <Button type="button" onClick={close}>
                {t("common:done")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            {hasLink ? <p className="text-sm">{t("subscribe.replaces")}</p> : null}
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={close}>
                {t("common:cancel")}
              </Button>
              <Button
                type="button"
                disabled={createLink.isPending}
                onClick={() =>
                  createLink.mutate({
                    name: t("subscribe.keyName", { name: calendar.name }).slice(0, KEY_NAME_MAX),
                    community_id: communityId,
                    resource_type: Tool.calendar,
                    resource_id: calendar.id,
                  })
                }
              >
                {hasLink ? t("subscribe.getNewLink") : t("subscribe.getLink")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
