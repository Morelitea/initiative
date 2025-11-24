import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "../api/client";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { queryClient } from "../lib/queryClient";

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

export const SettingsInterfacePage = () => {
  const interfaceQuery = useQuery({
    queryKey: ["interface-settings"],
    queryFn: async () => {
      const response = await apiClient.get<InterfaceSettings>("/settings/interface");
      return response.data;
    },
  });

  const updateInterface = useMutation({
    mutationFn: async (payload: InterfaceSettings) => {
      const response = await apiClient.put<InterfaceSettings>("/settings/interface", payload);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Interface settings updated");
      void queryClient.invalidateQueries({ queryKey: ["interface-settings"] });
    },
  });

  const [lightColor, setLightColor] = useState("#2563eb");
  const [darkColor, setDarkColor] = useState("#60a5fa");

  useEffect(() => {
    if (interfaceQuery.data) {
      setLightColor(interfaceQuery.data.light_accent_color);
      setDarkColor(interfaceQuery.data.dark_accent_color);
    }
  }, [interfaceQuery.data]);

  if (interfaceQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading interface settings…</p>;
  }

  if (interfaceQuery.isError) {
    return <p className="text-sm text-destructive">Unable to load interface settings.</p>;
  }

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateInterface.mutate({
      light_accent_color: lightColor,
      dark_accent_color: darkColor,
    });
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Interface</CardTitle>
        <CardDescription>Customize the accent color for both light and dark mode.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-6 md:grid-cols-2" onSubmit={handleSubmit}>
          <div className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="light-accent">Light mode accent</Label>
              <Input
                type="color"
                id="light-accent"
                className="h-10 w-16 cursor-pointer border-none bg-transparent p-0"
                value={lightColor}
                onChange={(event) => setLightColor(event.target.value)}
              />
            </div>
            <Input
              type="text"
              value={lightColor}
              onChange={(event) => setLightColor(event.target.value)}
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              Buttons, highlights, and focus states use this color while the app is in light mode.
            </p>
          </div>

          <div className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="dark-accent">Dark mode accent</Label>
              <Input
                type="color"
                id="dark-accent"
                className="h-10 w-16 cursor-pointer border-none bg-transparent p-0"
                value={darkColor}
                onChange={(event) => setDarkColor(event.target.value)}
              />
            </div>
            <Input
              type="text"
              value={darkColor}
              onChange={(event) => setDarkColor(event.target.value)}
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              Accent and primary elements use this color while dark mode is active.
            </p>
          </div>

          <CardFooter className="col-span-full flex flex-wrap gap-3">
            <Button type="submit" disabled={updateInterface.isPending}>
              {updateInterface.isPending ? "Saving…" : "Save interface settings"}
            </Button>
          </CardFooter>
        </form>
      </CardContent>
    </Card>
  );
};
