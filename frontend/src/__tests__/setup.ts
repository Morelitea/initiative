import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";

import { server } from "./helpers/msw-server";
import { resetFactories } from "./factories";

// ---------------------------------------------------------------------------
// Global Capacitor mocks – these modules are imported at the top level by many
// source files. Providing no-op stubs prevents "Cannot find module" errors in
// the jsdom test environment.
// ---------------------------------------------------------------------------

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => false,
    getPlatform: () => "web",
    convertFileSrc: (url: string) => url,
  },
}));

vi.mock("@capacitor/device", () => ({
  Device: {
    getInfo: vi.fn().mockResolvedValue({
      model: "test",
      platform: "web",
      operatingSystem: "unknown",
      osVersion: "0",
      manufacturer: "test",
      isVirtual: true,
      name: "Test Device",
    }),
    getId: vi.fn().mockResolvedValue({ identifier: "test-id" }),
  },
}));

vi.mock("@capacitor/browser", () => ({
  Browser: {
    open: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  },
}));

vi.mock("@capacitor/preferences", () => ({
  Preferences: {
    get: vi.fn().mockResolvedValue({ value: null }),
    set: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    keys: vi.fn().mockResolvedValue({ keys: [] }),
    clear: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock("@capacitor-community/safe-area", () => ({
  SafeArea: {
    enable: vi.fn().mockResolvedValue(undefined),
    disable: vi.fn().mockResolvedValue(undefined),
    getStatusBarHeight: vi.fn().mockResolvedValue({ statusBarHeight: 0 }),
    getSafeAreaInsets: vi.fn().mockResolvedValue({
      insets: { top: 0, right: 0, bottom: 0, left: 0 },
    }),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  },
}));

vi.mock("@capacitor/push-notifications", () => ({
  PushNotifications: {
    requestPermissions: vi.fn().mockResolvedValue({ receive: "granted" }),
    register: vi.fn().mockResolvedValue(undefined),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
    removeAllListeners: vi.fn().mockResolvedValue(undefined),
    getDeliveredNotifications: vi.fn().mockResolvedValue({ notifications: [] }),
  },
}));

vi.mock("@capacitor/app", () => ({
  App: {
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
    removeAllListeners: vi.fn().mockResolvedValue(undefined),
    getInfo: vi.fn().mockResolvedValue({ id: "test", name: "test", version: "0.0.0", build: "0" }),
    exitApp: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// jsdom shims – APIs not implemented in jsdom that components rely on
// ---------------------------------------------------------------------------

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ResizeObserver is used by many UI components (popovers, data tables, etc.)
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// ---------------------------------------------------------------------------
// MSW lifecycle
// ---------------------------------------------------------------------------

beforeAll(() => {
  server.listen({ onUnhandledRequest: "warn" });
});

afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});

afterAll(() => {
  server.close();
});

// ---------------------------------------------------------------------------
// Reset factory ID counters between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetFactories();
});
