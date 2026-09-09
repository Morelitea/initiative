/**
 * A three-method key/value store over IndexedDB, shaped to TanStack Query's
 * `AsyncStorage`.
 *
 * Deliberately not `@/lib/storage`: that module is backed by Capacitor
 * Preferences, which is the right home for small durable values (a token, a
 * theme) and the wrong home for a cache blob measured in hundreds of kilobytes
 * — SharedPreferences and UserDefaults rewrite the whole file on every set.
 * IndexedDB is the store built for this size, and losing it costs nothing: the
 * only thing kept here is a cache the app re-fetches the moment it has signal.
 */

interface IdbStore {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  removeItem: (key: string) => Promise<void>;
}

const request = <T>(req: IDBRequest<T>): Promise<T> =>
  new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

export const createIdbStore = (dbName: string, storeName: string): IdbStore => {
  let dbPromise: Promise<IDBDatabase> | null = null;

  const open = (): Promise<IDBDatabase> => {
    if (!dbPromise) {
      dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
        if (typeof indexedDB === "undefined") {
          reject(new Error("IndexedDB unavailable"));
          return;
        }
        const req = indexedDB.open(dbName, 1);
        req.onupgradeneeded = () => {
          if (!req.result.objectStoreNames.contains(storeName)) {
            req.result.createObjectStore(storeName);
          }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }).catch((error: unknown) => {
        // Don't cache the failure — a WebView that refused once (private mode,
        // a storage quota prompt) may well allow it after a relaunch.
        dbPromise = null;
        throw error;
      });
    }
    return dbPromise;
  };

  const withStore = async <T>(
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => IDBRequest<T>
  ): Promise<T> => {
    const db = await open();
    const tx = db.transaction(storeName, mode);
    const result = await request(run(tx.objectStore(storeName)));
    return result;
  };

  return {
    getItem: async (key) => {
      const value = await withStore<unknown>("readonly", (store) => store.get(key));
      return typeof value === "string" ? value : null;
    },
    setItem: async (key, value) => {
      await withStore("readwrite", (store) => store.put(value, key));
    },
    removeItem: async (key) => {
      await withStore("readwrite", (store) => store.delete(key));
    },
  };
};
