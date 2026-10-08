/**
 * The Android app keeps the Firebase settings it fetched for a server. When the
 * server names a different project, those settings are cleared before Firebase
 * starts, so the app fetches the new ones and registers a token they can reach.
 */
import { Capacitor } from "@capacitor/core";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";

import { syncFirebaseProject } from "./firebaseProject";

const runtime = vi.hoisted(() => ({ clearConfig: vi.fn(async () => ({ success: true })) }));
vi.mock("@/plugins/firebaseRuntime", () => ({ default: runtime }));

const SERVER = "https://initiative.example.com/api/v1";

const serving = (projectId: string | null) =>
  server.use(
    http.get("*/settings/fcm-config", () =>
      HttpResponse.json({ enabled: true, project_id: projectId })
    )
  );

describe("syncFirebaseProject", () => {
  beforeEach(() => {
    runtime.clearConfig.mockClear();
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("android");
  });

  it("fetches afresh the first time, then keeps settings while the project stays", async () => {
    serving("hosts-own-project");

    await syncFirebaseProject(SERVER);
    expect(runtime.clearConfig).toHaveBeenCalledTimes(1);

    await syncFirebaseProject(SERVER);
    expect(runtime.clearConfig).toHaveBeenCalledTimes(1);
  });

  it("clears the saved settings when the server moves to another project", async () => {
    serving("hosts-own-project");
    await syncFirebaseProject(SERVER);
    runtime.clearConfig.mockClear();

    serving("relay-project");
    await syncFirebaseProject(SERVER);

    expect(runtime.clearConfig).toHaveBeenCalledTimes(1);
  });

  it("leaves the settings alone when the server names no project or cannot be read", async () => {
    serving(null);
    await syncFirebaseProject(SERVER);
    server.use(http.get("*/settings/fcm-config", () => HttpResponse.error()));
    await syncFirebaseProject(SERVER);

    expect(runtime.clearConfig).not.toHaveBeenCalled();
  });

  it("does nothing on an iPhone, which has no Firebase", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    serving("relay-project");

    await syncFirebaseProject(SERVER);

    expect(runtime.clearConfig).not.toHaveBeenCalled();
  });
});
