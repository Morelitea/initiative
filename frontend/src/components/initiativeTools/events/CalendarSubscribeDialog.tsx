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

type SubscribableCalendar = { id: number; name: string };

type CalendarSubscribeDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  communityId: number;
  calendars: SubscribableCalendar[];
};

/**
 * Subscription links to calendars, for another calendar app: one link per
 * calendar, so each stays a calendar of its own there.
 *
 * A link is a personal API key that names its calendar, so it follows the
 * community's API-access setting, shows under Settings › Security, and is
 * shown once. Getting another replaces it.
 */
export const CalendarSubscribeDialog = ({
  open,
  onOpenChange,
  communityId,
  calendars,
}: CalendarSubscribeDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const [dialogKey, setDialogKey] = useState(0);
  const keysQuery = useMyApiKeys();
  const linked = new Set(
    (keysQuery.data?.keys ?? [])
      .filter((key) => key.resource_type === Tool.calendar && key.community_id === communityId)
      .map((key) => key.resource_id)
  );

  const close = () => {
    onOpenChange(false);
    // Links are shown once: closing forgets them.
    setDialogKey((key) => key + 1);
  };

  const [only] = calendars.length === 1 ? calendars : [];
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {only ? t("subscribe.title", { name: only.name }) : t("subscribe.titleMany")}
          </DialogTitle>
          <DialogDescription>{t("subscribe.description")}</DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">{t("subscribe.secret")}</p>
        <ul key={dialogKey} className="max-h-[50vh] space-y-3 overflow-y-auto">
          {calendars.map((calendar) => (
            <SubscribeRow
              key={calendar.id}
              communityId={communityId}
              calendar={calendar}
              hasLink={linked.has(calendar.id)}
              showName={!only}
            />
          ))}
        </ul>
        <p className="text-muted-foreground text-sm">{t("subscribe.manage")}</p>
        <DialogFooter>
          <Button type="button" onClick={close}>
            {t("common:done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/** One calendar's link: made on request and shown once. */
const SubscribeRow = ({
  communityId,
  calendar,
  hasLink,
  showName,
}: {
  communityId: number;
  calendar: SubscribableCalendar;
  hasLink: boolean;
  showName: boolean;
}) => {
  const { t } = useTranslation("calendars");
  const [link, setLink] = useState<string | null>(null);

  const createLink = useCreateApiKey({
    onSuccess: (data) => {
      const url = buildApiUrl(`c/${communityId}/calendars/${calendar.id}/feed.ics`);
      url.searchParams.set("token", data.secret);
      setLink(url.toString());
    },
    onError: (error) => toast.error(getErrorMessage(error, "calendars:subscribe.error")),
  });

  const copyLink = () => {
    if (!link || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(link).then(() => {
      toast.success(t("subscribe.copied"));
    });
  };

  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          {showName ? <p className="truncate font-medium">{calendar.name}</p> : null}
          {hasLink && !link ? (
            <p className="text-muted-foreground text-sm">{t("subscribe.replaces")}</p>
          ) : null}
        </div>
        {link ? null : (
          <Button
            type="button"
            size="sm"
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
        )}
      </div>
      {link ? (
        <>
          <code className="block break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm">
            {link}
          </code>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="outline" onClick={copyLink}>
              {t("subscribe.copy")}
            </Button>
            <Button type="button" size="sm" variant="outline" asChild>
              <a href={link.replace(/^https?:/, "webcal:")}>{t("subscribe.open")}</a>
            </Button>
          </div>
        </>
      ) : null}
    </li>
  );
};
