/// <reference lib="webworker" />

/**
 * Worker wrapper around the sandbox.
 *
 * The sandbox is already capability-free on its own; running it here keeps a
 * widget that spins from blocking paint, so a bad widget degrades to one dead
 * tile rather than a frozen canvas.
 *
 * The interpreter is compiled in this context, and both sandbox entry points —
 * rendering and reading a module's meta — are routed through here so it stays
 * that way. The response that serves this file carries the policy that permits
 * it (`backend/app/core/config.py`, `widget_sandbox_content_security_policy`).
 *
 * This file stays deliberately thin — all evaluation logic lives in
 * `sandbox.ts` so it can be tested directly, without worker plumbing.
 */

import {
  type RenderRequest,
  readMetaInSandbox,
  renderInSandbox,
  type SandboxResult,
} from "./sandbox";

export type SandboxWorkerRequest =
  | { id: number; kind: "render"; request: RenderRequest }
  | { id: number; kind: "meta"; source: string };

export interface SandboxWorkerResponse {
  id: number;
  result: SandboxResult;
}

self.onmessage = async (event: MessageEvent<SandboxWorkerRequest>) => {
  const message = event.data;
  const result =
    message.kind === "meta"
      ? await readMetaInSandbox(message.source)
      : await renderInSandbox(message.request);
  const response: SandboxWorkerResponse = { id: message.id, result };
  self.postMessage(response);
};
