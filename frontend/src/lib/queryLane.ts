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
 * How many statement reads one guild keeps in flight.
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

interface Lane {
  /** Reads in flight, including any let through by the ceiling. */
  running: number;
  /** Queued for a slot, oldest first. */
  waiting: { admit: () => void }[];
  /** The ceiling for the read at the head of the queue, or null when nothing
   *  is waiting. Only ever one: whoever is at the front is the only read whose
   *  patience is being measured. */
  timer: ReturnType<typeof setTimeout> | null;
}

/**
 * One lane per guild, because the limit being modelled is per guild.
 *
 * A shared lane would make one guild's slow canvas hold up another's, which the
 * server would have admitted — a tab that switches guild while the previous
 * dashboard's reads are still settling would queue the new one behind work it
 * has nothing to do with.
 */
const lanes = new Map<number, Lane>();

const laneFor = (guildId: number): Lane => {
  const existing = lanes.get(guildId);
  if (existing) return existing;
  const lane: Lane = { running: 0, waiting: [], timer: null };
  lanes.set(guildId, lane);
  return lane;
};

const disarm = (lane: Lane): void => {
  if (lane.timer === null) return;
  clearTimeout(lane.timer);
  lane.timer = null;
};

/**
 * Start the head of the queue's patience running.
 *
 * One timer for the queue rather than one per read, so a lane whose slots are
 * both stuck lets its backlog through **one read at a time**, each after its
 * own wait. Timers armed per read would all have been started in the same tick
 * by the same canvas and would therefore all come due together — releasing the
 * whole backlog at once, which is the burst this module exists to prevent.
 */
const arm = (lane: Lane): void => {
  if (lane.timer !== null || lane.waiting.length === 0) return;
  lane.timer = setTimeout(() => {
    lane.timer = null;
    const head = lane.waiting.shift();
    if (head) {
      // A slot that is not there, counted so it is given back on the way out.
      lane.running += 1;
      head.admit();
    }
    arm(lane);
  }, LANE_WAIT_CEILING_MS);
};

const enter = (lane: Lane): Promise<void> => {
  if (lane.running < LANE_WIDTH) {
    lane.running += 1;
    return Promise.resolve();
  }
  return new Promise<void>((admit) => {
    lane.waiting.push({ admit });
    arm(lane);
  });
};

/**
 * Hand the slot straight to whoever is next rather than releasing and
 * re-counting: the count only falls when the lane is actually empty, so two
 * callers resuming in the same tick cannot both read it as having room. The
 * ceiling restarts with the queue's new head, whose wait has only now begun.
 */
const leave = (lane: Lane, guildId: number): void => {
  const next = lane.waiting.shift();
  if (next) {
    disarm(lane);
    arm(lane);
    next.admit();
    return;
  }
  lane.running -= 1;
  disarm(lane);
  // Nothing running and nothing waiting: this guild is not being read right
  // now, and the lane is only a record of that. Safe to drop — a read still
  // holding a slot keeps `running` above zero, so the entry a caller is using
  // is never the one removed.
  if (lane.running <= 0) lanes.delete(guildId);
};

/** Run one statement read when that guild's lane has room for it. */
export const inQueryLane = async <T>(guildId: number, read: () => Promise<T>): Promise<T> => {
  const lane = laneFor(guildId);
  await enter(lane);
  try {
    return await read();
  } finally {
    leave(lane, guildId);
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
