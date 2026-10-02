import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

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

/** The server dropdown. Initiative Cloud is listed but not open yet. */
const ServerSelect = ({
  value,
  onValueChange,
  disabled,
}: {
  value: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  return (
    <>
      <Label htmlFor="server">{t("server.label")}</Label>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectTrigger id="server">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="cloud" disabled>
            {t("server.cloud")} · {t("server.cloudSoon")}
          </SelectItem>
          <SelectItem value="selfHosted">{t("server.selfHosted")}</SelectItem>
        </SelectContent>
      </Select>
    </>
  );
};

/**
 * Where the sign-in goes. A browser is on its server already, so it only
 * shows which kind, as do the pages a link opens for one server. Signing in
 * and up in the app pick one, with a self-hosted server's address under the
 * dropdown.
 */
export const ServerChoice = ({ pick = false }: { pick?: boolean }) => {
  const { isNativePlatform } = useServer();
  if (!isNativePlatform || !pick) {
    return (
      <div className="w-full space-y-2">
        <ServerSelect value="selfHosted" disabled />
      </div>
    );
  }
  return <ServerPicker />;
};

const ServerPicker = () => {
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
      // Leaving a server signs out of it, and a sign-up begun there stays there.
      if (user) await logout();
      await clearStart();
      setSelfHostedAddress(trimmed);
      await setServerUrl(trimmed);
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form className="w-full space-y-2" onSubmit={handleConnect}>
      <ServerSelect value={where} onValueChange={setWhere} />
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
