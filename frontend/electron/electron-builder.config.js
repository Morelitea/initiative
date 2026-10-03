const { readFileSync } = require("node:fs");
const { join } = require("node:path");

// The app is versioned with the rest of Initiative, from the VERSION file.
const version = readFileSync(join(__dirname, "..", "..", "VERSION"), "utf8").trim();

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: "com.morelitea.initiative",
  productName: "Initiative",
  extraMetadata: {
    name: "initiative",
    desktopName: "initiative.desktop",
    version,
    homepage: "https://github.com/Morelitea/initiative",
    author: { name: "Morelitea", email: "hello@morelitea.com" },
  },
  directories: {
    output: "dist",
    buildResources: "assets",
  },
  files: [
    "build/**/*",
    "app/**/*",
    "generated/**/*",
    // `assets` is also the buildResources directory, which is not packaged by
    // default; the splash screen is read from it at runtime.
    "assets/**/*",
    "package.json",
    // The platform runtime and plugins, prepared by `capacitor-electron vendor`.
    { from: "vendor/node_modules", to: "node_modules" },
  ],
  // Sign-in in the system browser hands back through initiative:// links.
  protocols: [{ name: "Initiative", schemes: ["initiative"] }],
  // Release assets are found by name: see `desktopInstallerUrl` in the frontend.
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    artifactName: "initiative-${version}-setup.${ext}",
  },
  mac: {
    target: [{ target: "dmg", arch: ["universal"] }],
    artifactName: "initiative-${version}.${ext}",
    category: "public.app-category.productivity",
    // Not signed with a developer certificate yet; an ad-hoc signature lets it run on Apple silicon.
    identity: "-",
  },
  linux: {
    target: [{ target: "deb", arch: ["x64"] }],
    artifactName: "initiative-${version}.${ext}",
    category: "Office",
    // Lets the desktop link the running window to the app's launcher entry.
    syncDesktopName: true,
  },
  publish: null,
};
