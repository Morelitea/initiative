// Runs before the first paint, from a plain <script> in index.html, so a dark
// reader never sees a white page while the app's modules are still arriving.
// Reads the same preference the ThemeProvider keeps (`initiative-theme` in
// localStorage: "light", "dark", or "system") and resolves "system" the same
// way, against prefers-color-scheme. The provider re-applies the class once it
// mounts, so this only decides the colour of the first frame.
(function () {
  try {
    var stored = window.localStorage.getItem("initiative-theme");
    var dark =
      stored === "dark" ||
      (stored !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) {
      document.documentElement.classList.add("dark");
    }
  } catch (_error) {
    // No storage (privacy mode, sandboxed frame): the page keeps the light default.
  }
})();
