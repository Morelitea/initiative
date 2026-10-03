import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { normalizeServerUrl, useServer } from "@/hooks/useServer";
import { getSelfHostedAddress, setSelfHostedAddress } from "@/lib/serverStorage";
import { clearStart } from "@/lib/startFlow";
import { cn } from "@/lib/utils";

/**
 * The kind of server a sign-in goes to, where it cannot be changed: in a
 * browser, which is on its server already, and on the app's pages that a
 * link opened for one server.
 */
export const ServerChip = () => {
  const { t } = useTranslation("auth");
  return (
    <p className="flex items-center gap-2 text-muted-foreground text-sm">
      {t("server.label")}
      <Badge variant="secondary">{t("server.selfHosted")}</Badge>
    </p>
  );
};

/**
 * Where signing in or up goes, inside its card. In the app a self-hosted
 * server takes an address, which the app keeps for next time. A browser is
 * on its server already, so there it is the chip.
 */
export const ServerPicker = ({ className }: { className?: string }) => {
  const { isNativePlatform } = useServer();
  if (isNativePlatform) return <AppServerPicker className={className} />;
  return (
    <div className={className}>
      <ServerChip />
    </div>
  );
};

const AppServerPicker = ({ className }: { className?: string }) => {
  const { t } = useTranslation("auth");
  const { serverUrl, setServerUrl, testServerConnection, getServerOrigin } = useServer();
  const { user, logout } = useAuth();
  // Initiative Cloud is not open yet, so self-hosted is the only choice.
  const [where, setWhere] = useState("selfHosted");
  const [address, setAddress] = useState(() => getSelfHostedAddress() ?? getServerOrigin() ?? "");
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const trimmed = address.trim();
  const isCurrent =
    serverUrl !== null && trimmed !== "" && normalizeServerUrl(trimmed) === serverUrl;

  const handleConnect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trimmed || isCurrent) return;
    setConnecting(true);
    setError(null);
    try {
      const result = await testServerConnection(trimmed);
      if (!result.valid) {
        setError(result.error ?? t("server.connectError"));
        return;
      }
      // A sign-up begun on one server stays there, and leaving a server signs
      // out of it. The draft goes first: if it cannot, nothing has changed.
      await clearStart();
      if (user) await logout();
      setSelfHostedAddress(trimmed);
      await setServerUrl(trimmed);
    } catch {
      setError(t("server.connectError"));
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form className={cn("space-y-2", className)} onSubmit={handleConnect}>
      <div className="flex items-center gap-2">
        <Label htmlFor="server" className="font-normal text-muted-foreground">
          {t("server.label")}
        </Label>
        <Select value={where} onValueChange={setWhere}>
          <SelectTrigger id="server" className="h-8 w-auto gap-2">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="cloud" disabled>
              {t("server.cloud")} · {t("server.cloudSoon")}
            </SelectItem>
            <SelectItem value="selfHosted">{t("server.selfHosted")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {where === "selfHosted" ? (
        <div className="flex gap-2">
          <Input
            aria-label={t("server.addressLabel")}
            type="url"
            placeholder={t("server.addressPlaceholder")}
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            autoCapitalize="none"
            autoCorrect="off"
            required
          />
          <Button type="submit" variant="outline" disabled={connecting || isCurrent}>
            {isCurrent ? t("server.connected") : t("server.connect")}
          </Button>
        </div>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </form>
  );
};
