/**
 * Frontend measurement: page views, uncaught errors and Web Vitals, sent to
 * the collector this deployment names (`AppConfig.faro_collector_url`).
 *
 * Nothing here runs until {@link startAnalytics} is called, which only
 * happens once the deployment names a collector and this browser granted the
 * `analytics` category. The SDK is imported then and not before, so a browser
 * that never agreed never downloads it.
 *
 * A page is named by its route template (`/c/$guildId/projects/$projectId`),
 * never by its address, and no person is attached to anything sent.
 */

import type { Faro, TransportItem } from "@grafana/faro-web-sdk";

let faro: Faro | null = null;
let loading: Promise<void> | null = null;
/** Whether sending is wanted right now, which can change while the SDK loads. */
let wanted = false;
/** The route template of the page on screen. */
let route = "unknown";

/**
 * Label an outgoing signal with the route template in place of the address
 * the SDK read from the location bar.
 */
export const labelWithRoute = (item: TransportItem): TransportItem => ({
  ...item,
  meta: { ...item.meta, page: { id: route, url: route } },
});

const pageView = () => faro?.api.pushEvent("page_view", undefined, undefined, { skipDedupe: true });

/** Start sending, or resume where measurement was paused. */
export const startAnalytics = (collectorUrl: string): Promise<void> => {
  wanted = true;
  if (faro) {
    faro.unpause();
    return Promise.resolve();
  }
  loading ??= import("@grafana/faro-web-sdk").then(
    ({
      initializeFaro,
      ErrorsInstrumentation,
      SessionInstrumentation,
      WebVitalsInstrumentation,
    }) => {
      faro = initializeFaro({
        url: collectorUrl,
        app: { name: "initiative", version: __APP_VERSION__ },
        // Errors, Web Vitals and the session they belong to. The console and
        // request timings are left out: both carry addresses and text.
        instrumentations: [
          new ErrorsInstrumentation(),
          new WebVitalsInstrumentation(),
          new SessionInstrumentation(),
        ],
        beforeSend: labelWithRoute,
        preventGlobalExposure: true,
        paused: !wanted,
      });
      if (wanted) pageView();
    }
  );
  return loading;
};

/** Stop sending. A loaded SDK cannot be unloaded, so it is paused, and
 *  whatever it records while paused is dropped rather than held. */
export const pauseAnalytics = (): void => {
  wanted = false;
  faro?.pause();
};

/** Record that a page is on screen, under its route template. */
export const recordPageView = (template: string): void => {
  route = template;
  pageView();
};
