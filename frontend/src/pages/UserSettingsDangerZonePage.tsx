import { useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { AlertTriangle, Unplug } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DeleteAccountDialog } from "@/components/user/DeleteAccountDialog";
import { useServer } from "@/hooks/useServer";
import type { User } from "@/types/api";

interface UserSettingsDangerZonePageProps {
  user: User;
  logout: () => void;
}

export const UserSettingsDangerZonePage = ({ user, logout }: UserSettingsDangerZonePageProps) => {
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const router = useRouter();
  const { isNativePlatform, getServerHostname, clearServerUrl } = useServer();

  const handleDeleteSuccess = () => {
    setDeleteDialogOpen(false);
    logout();
    router.navigate({ to: "/login" });
  };

  const handleDisconnectServer = async () => {
    await logout();
    clearServerUrl();
    router.navigate({ to: "/connect", replace: true });
  };

  return (
    <div className="space-y-6">
      {isNativePlatform && (
        <>
          <div className="flex items-center gap-3">
            <div className="bg-muted rounded-lg p-2">
              <Unplug className="text-muted-foreground h-6 w-6" />
            </div>
            <div>
              <p className="text-lg font-semibold">Server Connection</p>
              <p className="text-muted-foreground text-sm">
                Currently connected to {getServerHostname()}.
              </p>
            </div>
          </div>

          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle>Disconnect from Server</CardTitle>
              <CardDescription>
                Log out and disconnect from this server. You can connect to a different server
                afterward.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={handleDisconnectServer}>
                Disconnect
              </Button>
            </CardContent>
          </Card>
        </>
      )}

      <div className="flex items-center gap-3">
        <div className="bg-destructive/10 rounded-lg p-2">
          <AlertTriangle className="text-destructive h-6 w-6" />
        </div>
        <div>
          <p className="text-lg font-semibold">Danger Zone</p>
          <p className="text-muted-foreground text-sm">
            Irreversible and destructive actions for your account.
          </p>
        </div>
      </div>

      <Card className="border-destructive/50 shadow-sm">
        <CardHeader>
          <CardTitle className="text-destructive">Delete Account</CardTitle>
          <CardDescription>
            Permanently delete your account or deactivate it temporarily. This action affects your
            projects, documents, and other content.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="border-muted space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <h4 className="font-medium">Deactivate Account</h4>
                <p className="text-muted-foreground mt-1 text-sm">
                  Temporarily disable your account. You won&apos;t be able to log in, but all your
                  data will be preserved. An administrator can reactivate your account later.
                </p>
              </div>
            </div>
          </div>

          <div className="border-destructive/50 bg-destructive/5 space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <h4 className="text-destructive font-medium">Permanently Delete Account</h4>
                <p className="text-muted-foreground mt-1 text-sm">
                  Completely remove your account from the system. Projects will be transferred to
                  other users. Comments and documents will remain but show &ldquo;[Deleted
                  User]&rdquo;. <strong>This cannot be undone.</strong>
                </p>
              </div>
            </div>
          </div>

          <div className="border-t pt-4">
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              Delete Account
            </Button>
          </div>
        </CardContent>
      </Card>

      <DeleteAccountDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onSuccess={handleDeleteSuccess}
        user={user}
      />
    </div>
  );
};
