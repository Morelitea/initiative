/**
 * Main-thread client for the widget sandbox.
 *
 * Callers hand it a widget module and its data and get back a validated
 * `SceneSpec` or a machine code for the error tile. Everything between —
 * spawning the worker, framing the request, and surviving a worker that stops
 * answering — lives here so components never touch the runtime directly.
 *
 * Every call goes to the worker, which is where the interpreter is compiled.
 * The in-process path below serves environments with no `Worker` at all — jsdom
 * under test; in a browser it resolves to `WIDGET_RUNTIME_UNAVAILABLE`.
 */

import type { WidgetErrorCode } from "../errors";
import { type SceneValidation, validateScene } from "../validateScene";
import { validateWidgetMeta, type WidgetMeta } from "../widgetMeta";
import {
  DEFAULT_LIMITS,
  type RenderRequest,
  readMetaInSandbox,
  renderInSandbox,
  SandboxErrorCode,
  type SandboxResult,
} from "./sandbox";
import type { SandboxWorkerRequest, SandboxWorkerResponse } from "./sandbox.worker";

export type WidgetRenderOutcome =
  | { ok: true; spec: Extract<SceneValidation, { ok: true }>["spec"] }
  // A closed union rather than a bare string, so the error tile's lookup into
  // the locale file is checked at compile time.
  | { ok: false; code: WidgetErrorCode; detail?: string };

/** Slack over the sandbox's own deadline. The interrupt handler should always
 *  fire first; this only covers a worker that never answers at all (failed to
 *  boot, killed by the browser). */
const WORKER_GRACE_MS = 2_000;

interface Pending {
  resolve: (result: SandboxResult) => void;
  timer: ReturnType<typeof setTimeout>;
}

let worker: Worker | null = null;
let workerUnavailable = false;
let nextId = 1;
const pending = new Map<number, Pending>();

function settle(id: number, result: SandboxResult): void {
  const entry = pending.get(id);
  if (!entry) return;
  clearTimeout(entry.timer);
  pending.delete(id);
  entry.resolve(result);
}

/** Drops the worker and fails everything still in flight. The next call builds
 *  a fresh one, so a crashed worker costs one render rather than the session. */
function resetWorker(code: SandboxErrorCode, detail?: string): void {
  worker?.terminate();
  worker = null;
  for (const id of [...pending.keys()]) settle(id, { ok: false, code, detail });
}

function getWorker(): Worker | null {
  if (workerUnavailable) return null;
  if (worker) return worker;
  if (typeof Worker === "undefined") {
    workerUnavailable = true;
    return null;
  }
  try {
    worker = new Worker(new URL("./sandbox.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (event: MessageEvent<SandboxWorkerResponse>) => {
      settle(event.data.id, event.data.result);
    };
    worker.onerror = (event) => {
      resetWorker(SandboxErrorCode.UNAVAILABLE, event.message);
    };
    return worker;
  } catch (error) {
    // No worker (an old browser, a restrictive embedding, jsdom under test).
    // The sandbox is what provides isolation, so running it inline is still
    // fully sandboxed — it only gives up not blocking paint, which the
    // interrupt deadline already bounds.
    workerUnavailable = true;
    void error;
    return null;
  }
}

/** Tear down the runtime. Tests use it between cases; the app calls it when the
 *  last dashboard unmounts. */
export function disposeWidgetHost(): void {
  resetWorker(SandboxErrorCode.UNAVAILABLE);
  workerUnavailable = false;
}

/** Send one request to the worker and wait for its answer. `inline` is the same
 *  work done in-process, for the no-`Worker` case described at the top. */
async function evaluate(
  frame: (id: number) => SandboxWorkerRequest,
  inline: () => Promise<SandboxResult>,
  timeoutMs = DEFAULT_LIMITS.timeoutMs
): Promise<SandboxResult> {
  const host = getWorker();
  if (!host) return inline();

  const id = nextId++;
  const budget = timeoutMs + WORKER_GRACE_MS;

  return new Promise<SandboxResult>((resolve) => {
    const timer = setTimeout(() => {
      // The worker never answered — assume it is wedged and rebuild it, rather
      // than leaving every later render queued behind a dead one.
      resetWorker(SandboxErrorCode.TIMEOUT);
    }, budget);
    pending.set(id, { resolve, timer });
    host.postMessage(frame(id));
  });
}

/**
 * Run a widget and validate what it drew.
 *
 * Never throws and never returns unvalidated output: a widget that fails, times
 * out, or emits something outside the vocabulary comes back as a code the tile
 * renders as an error.
 */
export async function renderWidget(request: RenderRequest): Promise<WidgetRenderOutcome> {
  const framed: RenderRequest = {
    ...request,
    // Widgets that mark work late need to know "now". Rounding to the minute
    // keeps the render stable across re-renders — the sandbox default of 0 is
    // deliberately inert so tests state their own clock.
    now: request.now ?? Math.floor(Date.now() / 60_000) * 60_000,
  };
  const result = await evaluate(
    (id) => ({ id, kind: "render", request: framed }),
    () => renderInSandbox(framed),
    framed.limits?.timeoutMs
  );
  if (!result.ok) return { ok: false, code: result.code, detail: result.detail };

  const validation = validateScene(result.value);
  if (!validation.ok) return { ok: false, code: validation.code };
  return { ok: true, spec: validation.spec };
}

// Meta is static per module, so it is read once and kept. Keyed by the module
// source itself, which means an updated listing version is a different key
// rather than a stale entry.
const metaCache = new Map<string, WidgetMeta | null>();

/** Outcomes that describe the runtime rather than the module: a worker that
 *  never booted, or one that stopped answering and was rebuilt. Reading again
 *  can give a different answer, so these are the two the cache does not keep —
 *  every other failure is a property of the source and would only repeat. */
const RUNTIME_META_FAILURES: ReadonlySet<SandboxErrorCode> = new Set([
  SandboxErrorCode.UNAVAILABLE,
  SandboxErrorCode.TIMEOUT,
]);

/**
 * A widget's own name, description, and option labels.
 *
 * Read through the sandbox under the same bounds a render gets, then rebuilt by
 * `validateWidgetMeta` — a module's metadata is untrusted input like anything
 * else it produces. Returns `null` when the module declares none, which is not
 * an error: callers fall back to the widget's type id.
 *
 * A widget that could not be read *this time* falls back to its type id for now
 * and is read again on the next ask, rather than wearing that id for the rest of
 * the session.
 */
export async function readWidgetMeta(source: string): Promise<WidgetMeta | null> {
  const cached = metaCache.get(source);
  if (cached !== undefined) return cached;

  const result = await evaluate(
    (id) => ({ id, kind: "meta", source }),
    () => readMetaInSandbox(source)
  );
  const meta = result.ok ? validateWidgetMeta(result.value) : null;
  if (result.ok || !RUNTIME_META_FAILURES.has(result.code)) {
    metaCache.set(source, meta);
  }
  return meta;
}
