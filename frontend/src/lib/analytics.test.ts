import type { TransportItem } from "@grafana/faro-web-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => {
  const faro = { api: { pushEvent: vi.fn() }, pause: vi.fn(), unpause: vi.fn() };
  return {
    faro,
    initializeFaro: vi.fn(
      (_config: { url: string; paused: boolean; instrumentations: object[] }) => faro
    ),
    ErrorsInstrumentation: class ErrorsInstrumentation {},
    SessionInstrumentation: class SessionInstrumentation {},
    WebVitalsInstrumentation: class WebVitalsInstrumentation {},
  };
});

vi.mock("@grafana/faro-web-sdk", () => sdk);

// Module state is the point under test, so each case starts from a fresh copy.
const load = () => import("@/lib/analytics");

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

describe("frontend measurement", () => {
  it("sends nothing until started", async () => {
    const { recordPageView } = await load();

    recordPageView("/c/$communityId/projects/$projectId");

    expect(sdk.initializeFaro).not.toHaveBeenCalled();
  });

  it("starts with errors, Web Vitals and sessions only, and records the page", async () => {
    const { startAnalytics } = await load();

    await startAnalytics("/collect");

    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
    const [config] = sdk.initializeFaro.mock.calls[0];
    expect(config.url).toBe("/collect");
    expect(config.paused).toBe(false);
    expect(config.instrumentations.map((i) => i.constructor.name)).toEqual([
      "ErrorsInstrumentation",
      "WebVitalsInstrumentation",
      "SessionInstrumentation",
    ]);
    expect(sdk.faro.api.pushEvent).toHaveBeenCalledWith("page_view", undefined, undefined, {
      skipDedupe: true,
    });
  });

  it("names the page by its route template, never its address", async () => {
    const { labelWithRoute, recordPageView } = await load();
    recordPageView("/c/$communityId/projects/$projectId");

    const item = {
      type: "event",
      payload: {},
      meta: { page: { url: "https://app.example.com/c/4/projects/9?tab=board" }, app: {} },
    } as unknown as TransportItem;

    expect(labelWithRoute(item).meta).toEqual({
      page: {
        id: "/c/$communityId/projects/$projectId",
        url: "/c/$communityId/projects/$projectId",
      },
      app: {},
    });
  });

  it("starts paused when consent is withdrawn while the SDK loads", async () => {
    const { pauseAnalytics, startAnalytics } = await load();

    const started = startAnalytics("/collect");
    pauseAnalytics();
    await started;

    expect(sdk.initializeFaro.mock.calls[0][0].paused).toBe(true);
    expect(sdk.faro.api.pushEvent).not.toHaveBeenCalled();
  });

  it("pauses and resumes the one loaded SDK", async () => {
    const { pauseAnalytics, startAnalytics } = await load();
    await startAnalytics("/collect");

    pauseAnalytics();
    await startAnalytics("/collect");

    expect(sdk.faro.pause).toHaveBeenCalledOnce();
    expect(sdk.faro.unpause).toHaveBeenCalledOnce();
    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
  });

  it("stops sending when the deployment names another collector", async () => {
    const { startAnalytics } = await load();
    await startAnalytics("/collect");

    await startAnalytics("https://faro.example.com/collect");

    expect(sdk.faro.pause).toHaveBeenCalledOnce();
    expect(sdk.faro.unpause).not.toHaveBeenCalled();
    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
  });

  it("tries again after the SDK fails to start", async () => {
    const { startAnalytics } = await load();
    sdk.initializeFaro.mockImplementationOnce(() => {
      throw new Error("blocked");
    });

    await startAnalytics("/collect");
    await startAnalytics("/collect");

    expect(sdk.initializeFaro).toHaveBeenCalledTimes(2);
    expect(sdk.faro.api.pushEvent).toHaveBeenCalledOnce();
  });
});
