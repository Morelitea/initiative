import { AxiosError, AxiosHeaders } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { busyRetryDelay, inQueryLane, isQueryBusy, retryWhileBusy } from "./queryLane";

/** An AxiosError carrying the body the API actually returns. */
function apiError(status: number, detail?: string): AxiosError {
  const error = new AxiosError("request failed", "ERR_BAD_REQUEST");
  error.response = {
    status,
    statusText: "",
    data: detail === undefined ? {} : { detail },
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
}

/** A read that finishes only when the test says so. */
function pending<T>(value: T) {
  let settle!: (result: T) => void;
  const promise = new Promise<T>((resolve) => {
    settle = resolve;
  });
  return { promise, settle: () => settle(value) };
}

const flush = () => new Promise<void>((done) => setTimeout(done, 0));

const GUILD = 3;
const OTHER_GUILD = 4;

afterEach(() => {
  vi.useRealTimers();
});

describe("inQueryLane", () => {
  it("holds a canvas of reads to the slots the guild actually has", async () => {
    const reads = [pending(1), pending(2), pending(3), pending(4), pending(5)];
    const started: number[] = [];

    const all = reads.map((read, index) =>
      inQueryLane(GUILD, () => {
        started.push(index);
        return read.promise;
      })
    );
    await flush();

    // Five tiles opened together; only the first two are asking.
    expect(started).toEqual([0, 1]);

    reads[0].settle();
    await flush();
    expect(started).toEqual([0, 1, 2]);

    for (const read of reads) read.settle();
    await expect(Promise.all(all)).resolves.toEqual([1, 2, 3, 4, 5]);
    expect(started).toEqual([0, 1, 2, 3, 4]);
  });

  it("does not make one guild wait behind another's reads", async () => {
    // The limit being modelled is per guild, so a tab that switches guild must
    // not queue the new dashboard behind the old one's still-settling reads.
    const held = [pending("a"), pending("b")];
    const busy = held.map((read) => inQueryLane(GUILD, () => read.promise));

    const elsewhere = vi.fn(() => Promise.resolve("elsewhere"));
    await expect(inQueryLane(OTHER_GUILD, elsewhere)).resolves.toBe("elsewhere");

    for (const read of held) read.settle();
    await Promise.all(busy);
  });

  it("lets a read through rather than queueing it behind one that never ends", async () => {
    vi.useFakeTimers();
    const lost = pending("never");
    const blocking = [
      inQueryLane(GUILD, () => lost.promise),
      inQueryLane(GUILD, () => lost.promise),
    ];
    const behind = pending("through");
    const started = vi.fn(() => behind.promise);
    const queued = inQueryLane(GUILD, started);

    await vi.advanceTimersByTimeAsync(14_000);
    expect(started).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2_000);
    expect(started).toHaveBeenCalled();

    behind.settle();
    await expect(queued).resolves.toBe("through");

    // The lane is not left short: once the stuck reads end, it is empty again.
    lost.settle();
    await Promise.all(blocking);
    const next = vi.fn(() => Promise.resolve("free"));
    await expect(inQueryLane(GUILD, next)).resolves.toBe("free");
  });

  it("releases a stuck lane's backlog one read at a time, not all at once", async () => {
    // Everything queued by one canvas was queued in the same tick, so timers
    // armed per read would all come due together and fire the whole backlog —
    // the burst this module exists to prevent.
    vi.useFakeTimers();
    const lost = pending("never");
    const blocking = [
      inQueryLane(GUILD, () => lost.promise),
      inQueryLane(GUILD, () => lost.promise),
    ];
    const backlog = [pending("x"), pending("y"), pending("z")];
    const started: number[] = [];
    const queued = backlog.map((read, index) =>
      inQueryLane(GUILD, () => {
        started.push(index);
        return read.promise;
      })
    );

    await vi.advanceTimersByTimeAsync(16_000);
    expect(started).toEqual([0]);

    await vi.advanceTimersByTimeAsync(16_000);
    expect(started).toEqual([0, 1]);

    await vi.advanceTimersByTimeAsync(16_000);
    expect(started).toEqual([0, 1, 2]);

    for (const read of backlog) read.settle();
    lost.settle();
    await Promise.all([...queued, ...blocking]);
  });

  it("gives the slot back when a read fails", async () => {
    const failing = inQueryLane(GUILD, () => Promise.reject(new Error("refused")));
    await expect(failing).rejects.toThrow("refused");

    const held = pending("a");
    const blocking = inQueryLane(GUILD, () => held.promise);
    const after = pending("b");
    const started = vi.fn(() => after.promise);
    const queued = inQueryLane(GUILD, started);
    await flush();

    // One slot is held; the other was handed back, so this one is free to run.
    expect(started).toHaveBeenCalled();

    held.settle();
    after.settle();
    await expect(Promise.all([blocking, queued])).resolves.toEqual(["a", "b"]);
  });
});

describe("retryWhileBusy", () => {
  it("comes back when the guild had no free slot", () => {
    expect(isQueryBusy(apiError(429, "QUERY_BUSY"))).toBe(true);
    expect(retryWhileBusy(0, apiError(429, "QUERY_BUSY"))).toBe(true);
  });

  it("gives up rather than hammering a guild that stays busy", () => {
    expect(retryWhileBusy(4, apiError(429, "QUERY_BUSY"))).toBe(false);
  });

  it("does not retry a statement that was refused on its own terms", () => {
    expect(retryWhileBusy(0, apiError(400, "QUERY_TOO_EXPENSIVE"))).toBe(false);
    expect(retryWhileBusy(0, apiError(504, "QUERY_TIMED_OUT"))).toBe(false);
    expect(retryWhileBusy(0, apiError(403))).toBe(false);
  });

  it("does not retry the rate limiter, which answers 429 without a code", () => {
    expect(retryWhileBusy(0, apiError(429))).toBe(false);
  });

  it("backs off further each time, up to a ceiling", () => {
    expect(busyRetryDelay(0)).toBeGreaterThanOrEqual(250);
    expect(busyRetryDelay(1)).toBeGreaterThanOrEqual(500);
    expect(busyRetryDelay(9)).toBeLessThanOrEqual(4_250);
  });
});
