// The browser globals the editor's modules read as they load, for an engine
// that has none. Nothing here is called while a document is read or written,
// except `crypto`, which Yjs draws ids from: the server names the client a
// state is written as, so these never become a document's ids.
const nothing = () => {};
Object.assign(globalThis, {
  self: globalThis,
  global: globalThis,
  console: { log: nothing, info: nothing, warn: nothing, error: nothing, debug: nothing },
  queueMicrotask: (callback) => Promise.resolve().then(callback),
  setTimeout: () => 0,
  clearTimeout: nothing,
  setInterval: () => 0,
  clearInterval: nothing,
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: nothing,
  addEventListener: nothing,
  removeEventListener: nothing,
  navigator: { userAgent: "server", platform: "server", language: "en", languages: ["en"] },
  location: {
    href: "http://server/",
    origin: "http://server",
    protocol: "http:",
    host: "server",
    hostname: "server",
    pathname: "/",
    search: "",
    hash: "",
  },
  AbortController: class {
    signal = { aborted: false, addEventListener: nothing, removeEventListener: nothing };
    abort() {}
  },
  crypto: {
    getRandomValues(array) {
      for (let i = 0; i < array.length; i++) {
        array[i] = Math.floor(Math.random() * 256 ** (array.BYTES_PER_ELEMENT || 1));
      }
      return array;
    },
  },
});
