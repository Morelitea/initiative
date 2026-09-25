/**
 * How long a socket waits before trying again.
 *
 * Full jitter: a random wait between nothing and a ceiling that doubles with
 * each attempt, up to `capMs`. When a server restarts, every tab it was
 * holding notices at the same moment; a fixed or merely growing delay brings
 * them all back at the same moment too. Spreading each attempt over the whole
 * window is what keeps a restart from becoming a stampede.
 */
export const reconnectDelay = (attempt: number, baseMs: number, capMs: number): number =>
  Math.random() * Math.min(capMs, baseMs * 2 ** Math.max(0, attempt));
