import { getErrorCode, getHttpStatus } from "@/lib/errorMessage";

/**
 * How a canvas of tiles asks the database more than it is allowed to at once.
 *
 * A guild may have only so many reader-written statements running at a time
 * (`QUERY_MAX_CONCURRENT_PER_GUILD`), and the server refuses the rest outright
 * rather than queueing them — a slot is an advisory lock taken without waiting,
 * so nothing holds a connection idle. That is the right answer to a request it
 * cannot serve, and the wrong shape for a dashboard: opening one fires every
 * widget's read in the same tick, so a canvas of five tiles asks for five slots
 * and three of them come back refused before the first has finished.
 *
 * So the queueing the server declines to do happens here, where the tiles are.
 * The lane lets a few reads run and holds the rest until one finishes, in the
 * order they were asked. A refusal that still gets through — another tab, or
 * somebody else in the same guild — is retried rather than shown, because
 * "everyone's slots are full" is a statement about this moment and not about
 * the query.
 */

/**
 * How many statement reads this tab keeps in flight.
 *
 * Matched to the server's per-guild default so the common case — one reader,
 * one canvas — never asks for a slot that is not there. An operator who raises
 * `QUERY_MAX_CONCURRENT_PER_GUILD` loses nothing but a little parallelism; one
 * who lowers it falls back to the retry below.
 */
const LANE_WIDTH = 2;

/**
 * How long a read waits for a slot before going anyway.
 *
 * The lane holds a read while another finishes, and nothing here knows how long
 * that takes — a request has no timeout of its own, so one that never comes
 * back would otherwise hold its slot, and the whole canvas behind it, for as
 * long as the tab is open. Past this the read is let through regardless: it may
 * be refused, and a refusal it can retry is a better answer than a spinner
 * nothing will ever end.
 */
const LANE_WAIT_CEILING_MS = 15_000;

let running = 0;

/**
 * The reads queued for a slot, oldest first. Each returns whether it took the
 * slot offered — one that already let itself through declines, and the slot
 * goes to whoever is behind it.
 */
const waiting: (() => boolean)[] = [];

const enter = (): Promise<void> => {
  if (running < LANE_WIDTH) {
    running += 1;
    return Promise.resolve();
  }
  return new Promise<void>((admit) => {
    let admitted = false;
    const claim = (): boolean => {
      if (admitted) return false;
      admitted = true;
      return true;
    };
    const ceiling = setTimeout(() => {
      // Nobody handed a slot over in time, so this read takes one that is not
      // there and says so in the count.
      if (claim()) {
        running += 1;
        admit();
      }
    }, LANE_WAIT_CEILING_MS);
    waiting.push(() => {
      if (!claim()) return false;
      clearTimeout(ceiling);
      admit();
      return true;
    });
  });
};

/**
 * Hand the slot straight to whoever is next rather than releasing and
 * re-counting: the count only falls when the lane is actually empty, so two
 * callers resuming in the same tick cannot both read it as having room.
 */
const leave = (): void => {
  while (waiting.length > 0) {
    if (waiting.shift()?.()) return;
  }
  running -= 1;
};

/** Run one statement read when the lane has room for it. */
export const inQueryLane = async <T>(read: () => Promise<T>): Promise<T> => {
  await enter();
  try {
    return await read();
  } finally {
    leave();
  }
};

/** The refusal that means "not now", as opposed to "not this statement". */
export const isQueryBusy = (error: unknown): boolean =>
  getHttpStatus(error) === 429 && getErrorCode(error) === "QUERY_BUSY";

/**
 * Retry a busy guild, and nothing else.
 *
 * A statement either resolves against the registry or it does not, and a
 * refused one is refused the same way every time — so every other failure is
 * final. Slots are the exception: they free as other reads finish.
 */
export const retryWhileBusy = (failureCount: number, error: unknown): boolean =>
  isQueryBusy(error) && failureCount < 4;

/**
 * Back off, with jitter, so readers that were refused together do not come
 * back together.
 */
export const busyRetryDelay = (failureCount: number): number =>
  Math.min(250 * 2 ** failureCount, 4_000) + Math.random() * 250;
