// What the server's editor imports in place of a library only the browser's
// views use: every property is this same function, and calling it or
// constructing it gives it back.
const stub = new Proxy(function stub() {}, {
  get: (_target, key) => (key === "__esModule" ? true : stub),
  apply: () => stub,
  construct: () => stub,
});
module.exports = stub;
