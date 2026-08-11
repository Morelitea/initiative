/// <reference lib="webworker" />

/**
 * Worker wrapper around the sandbox.
 *
 * The sandbox is already capability-free on its own; running it here buys two
 * further things. A widget that spins cannot block paint, so a bad widget
 * degrades to one dead tile rather than a frozen canvas. And a hypothetical
 * QuickJS escape lands in a worker with no DOM instead of in the page.
 *
 * This file stays deliberately thin — all evaluation logic lives in
 * `sandbox.ts` so it can be tested directly, without worker plumbing.
 */

import { type RenderRequest, renderInSandbox, type SandboxResult } from "./sandbox";

export interface SandboxWorkerRequest {
  id: number;
  request: RenderRequest;
}

export interface SandboxWorkerResponse {
  id: number;
  result: SandboxResult;
}

self.onmessage = async (event: MessageEvent<SandboxWorkerRequest>) => {
  const { id, request } = event.data;
  const result = await renderInSandbox(request);
  const response: SandboxWorkerResponse = { id, result };
  self.postMessage(response);
};
