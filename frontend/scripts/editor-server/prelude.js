// The browser globals the editor's modules, and the template compiler's, read as
// they load, for an engine that has none. Nothing here is called while a document is read or written,
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
  // UTF-8 only, which is all there is: the template compiler's CEL parser makes
  // one as it loads, to read bytes literals.
  TextEncoder: class {
    encoding = "utf-8";
    encode(text = "") {
      const bytes = [];
      for (const character of String(text)) {
        const code = character.codePointAt(0);
        if (code < 0x80) bytes.push(code);
        else if (code < 0x800) bytes.push(0xc0 | (code >> 6), 0x80 | (code & 63));
        else if (code < 0x10000) {
          bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
        } else {
          bytes.push(
            0xf0 | (code >> 18),
            0x80 | ((code >> 12) & 63),
            0x80 | ((code >> 6) & 63),
            0x80 | (code & 63)
          );
        }
      }
      return new Uint8Array(bytes);
    }
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
