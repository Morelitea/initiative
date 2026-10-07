// Write the third-party licence notices the app ships with.
//
//   node scripts/third-party-notices.mjs [out-file]
//
// Every `vite build` runs this too (see `thirdPartyNoticesPlugin` in
// vite.config.ts) and emits the result as dist/THIRD_PARTY_NOTICES.txt, so the
// web app, the OTA bundle and the phone and desktop apps all carry it. The
// version dialog links to it (Open-source licences), and the /licences page
// renders it. Nothing it writes is committed.
//
// Most of what the app ships is open source under terms (MIT, BSD, ISC,
// Apache-2.0, MPL-2.0, EPL-2.0, OFL-1.1, ...) that ask for the copyright and
// licence notice to travel with every copy. Minified bundles strip them, so
// this collects them again, in four parts:
//
//   1. Every production JavaScript package installed, read from node_modules:
//      name, version, licence, and the package's own LICENSE/NOTICE files,
//      verbatim. Identical texts are printed once, under every package that
//      shares them. A package that ships no licence file gets the standard
//      text from licences/texts/, and says so.
//   2. The native code in the iOS and Android apps: the Capacitor plug-ins, and
//      the Swift and Gradle libraries they and the app pull in. Those are not
//      npm packages, so licences/native.json lists them by hand, and the build
//      fails when a Capacitor plug-in in package.json is missing from it.
//   3. Fonts the build emits, from licences/fonts.json. The build fails when it
//      emits a font file that no entry there claims.
//   4. The artwork credited in the repository's NOTICE.md, verbatim.
//
// Choices a human made (which side of a dual licence we take, a licence a
// package's metadata leaves out) live in licences/overrides.json.
import {
  existsSync,
  readdirSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export const HEADER = "Initiative includes the following third-party software and artwork.";
export const OWN_LICENCE =
  "Initiative itself is licensed under the GNU Affero General Public License, version 3 " +
  "(AGPL-3.0). Its source code is at https://github.com/beyonders-studio/initiative";

const RULE = "=".repeat(80);
const THIN_RULE = "-".repeat(80);

// --- Reading a package -------------------------------------------------------

// LICENSE, LICENCE, COPYING, NOTICE, with or without an extension or a suffix
// (LICENSE.md, LICENSE-MIT, license.txt, NOTICE.txt).
const LICENCE_FILE = /^(licen[cs]e|copying|notice)([._-].*)?$/i;
const NOTICE_FILE = /^notice([._-].*)?$/i;

/** The licence and notice files at the top of a package, licences first. */
export const findLicenceFiles = (dir) =>
  readdirSync(dir)
    .filter((name) => LICENCE_FILE.test(name) && statSync(join(dir, name)).isFile())
    .sort((a, b) => {
      const noticeA = NOTICE_FILE.test(a);
      const noticeB = NOTICE_FILE.test(b);
      if (noticeA !== noticeB) return noticeA ? 1 : -1;
      return a.localeCompare(b);
    });

/** The SPDX expression a package.json declares, in any of its historical shapes. */
export const declaredLicence = (pkg) => {
  const { license, licenses } = pkg;
  if (typeof license === "string" && license.trim()) return license.trim();
  if (license && typeof license === "object" && license.type) return String(license.type);
  if (Array.isArray(licenses) && licenses.length > 0) {
    const ids = licenses.map((l) => (typeof l === "string" ? l : l?.type)).filter(Boolean);
    if (ids.length === 1) return ids[0];
    if (ids.length > 1) return `(${ids.join(" OR ")})`;
  }
  return null;
};

const repositoryUrl = (pkg) => {
  const repo = typeof pkg.repository === "string" ? pkg.repository : pkg.repository?.url;
  if (repo) {
    return repo
      .replace(/^git\+/, "")
      .replace(/^git:\/\//, "https://")
      .replace(/^github:/, "https://github.com/")
      .replace(/\.git$/, "")
      .replace(/^([\w.-]+\/[\w.-]+)$/, "https://github.com/$1");
  }
  return pkg.homepage ?? null;
};

const authorName = (pkg) => {
  const { author } = pkg;
  if (typeof author === "string") return author;
  return author?.name ?? null;
};

// Node's own lookup: the nearest node_modules/<name> above the dependent.
// pnpm keeps a package's dependencies beside it under .pnpm/<pkg>/node_modules,
// which this finds the same way Node does.
const resolvePackageDir = (fromDir, name) => {
  for (let dir = fromDir; ; dir = dirname(dir)) {
    if (basename(dir) !== "node_modules") {
      const candidate = join(dir, "node_modules", name);
      if (existsSync(join(candidate, "package.json"))) return realpathSync(candidate);
    }
    if (dirname(dir) === dir) return null;
  }
};

const readJson = (file) => JSON.parse(readFileSync(file, "utf-8"));

/**
 * Every package a production install of `rootDir` pulls in: its
 * `dependencies`, and theirs, all the way down. Optional and peer dependencies
 * count when they are installed (a platform's native binary, react-is) and are
 * skipped when they are not. `buildOnly` names direct dependencies that only
 * run at build time; they, and what only they pull in, are left out. Even so
 * this casts wider than the bundle, which errs the safe way.
 */
export const collectPackages = (rootDir, { buildOnly = [] } = {}) => {
  const root = readJson(join(rootDir, "package.json"));
  const seen = new Map();
  const shipped = Object.keys(root.dependencies ?? {}).filter((name) => !buildOnly.includes(name));
  const queue = shipped.map((name) => ({
    name,
    from: rootDir,
    optional: false,
  }));
  for (const name of Object.keys(root.optionalDependencies ?? {})) {
    queue.push({ name, from: rootDir, optional: true });
  }
  while (queue.length > 0) {
    const { name, from, optional } = queue.shift();
    const dir = resolvePackageDir(from, name);
    if (!dir) {
      if (optional) continue;
      throw new Error(`third-party-notices: ${name} is a dependency but is not installed`);
    }
    if (seen.has(dir)) continue;
    const pkg = readJson(join(dir, "package.json"));
    seen.set(dir, {
      name: pkg.name ?? name,
      version: pkg.version ?? "0.0.0",
      licence: declaredLicence(pkg),
      author: authorName(pkg),
      source: repositoryUrl(pkg),
      dir,
      capacitorPlugin: Boolean(pkg.capacitor),
    });
    for (const dep of Object.keys(pkg.dependencies ?? {})) {
      queue.push({ name: dep, from: dir, optional: false });
    }
    // Required peers too, where installed: recharts reaches react-is that way,
    // and it ends up in the bundle like any other dependency. Optional peers
    // are integrations a package uses if they happen to be there (TypeScript
    // for Lexical, Sass for Vite), so they are left to whoever installs them.
    const peerMeta = pkg.peerDependenciesMeta ?? {};
    const requiredPeers = Object.keys(pkg.peerDependencies ?? {}).filter(
      (dep) => !peerMeta[dep]?.optional
    );
    for (const dep of [...Object.keys(pkg.optionalDependencies ?? {}), ...requiredPeers]) {
      queue.push({ name: dep, from: dir, optional: true });
    }
  }
  // Two directories can hold one name@version (pnpm keys a copy by its peers).
  const unique = new Map();
  for (const entry of seen.values()) {
    const key = `${entry.name}@${entry.version}`;
    if (!unique.has(key)) unique.set(key, entry);
  }
  return [...unique.values()].sort(comparePackages);
};

const comparePackages = (a, b) =>
  a.name.localeCompare(b.name) || a.version.localeCompare(b.version, undefined, { numeric: true });

// --- Turning packages into notices -------------------------------------------

const normaliseText = (text) =>
  text
    .replace(/^﻿/, "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .trim();

/**
 * One package's licence id and the text that goes with it.
 *
 * `readFile(dir, name)` and `listFiles(dir)` are injected so the rules can be
 * tested without a node_modules; `standardText(id)` returns the stock text for
 * an SPDX id, or null when licences/texts/ has none.
 */
export const resolveNotice = (entry, { overrides, listFiles, readFile, standardText }) => {
  const override = overrides[entry.name] ?? {};
  const licence = override.licence ?? entry.licence;
  const files = override.files ?? listFiles(entry.dir);
  const extraFiles = override.extraFiles ?? [];
  const parts = [...files, ...extraFiles].map((name) => {
    const text = normaliseText(readFile(entry.dir, name));
    return files.length + extraFiles.length > 1 ? `[${name}]\n\n${text}` : text;
  });
  const note = override.note ?? null;
  if (parts.length > 0) {
    if (!licence) {
      throw new Error(
        `third-party-notices: ${entry.name}@${entry.version} declares no licence; ` +
          "name it in licences/overrides.json"
      );
    }
    return { licence, text: parts.join("\n\n"), fallback: false, note };
  }
  const stock = licence ? standardText(licence) : null;
  if (!stock) {
    throw new Error(
      `third-party-notices: ${entry.name}@${entry.version} ships no licence file and ` +
        `licences/texts/ has no standard text for "${licence ?? "no licence"}"; ` +
        "add one, or an entry in licences/overrides.json"
    );
  }
  const holder = entry.author ? ` Its author, per its package.json: ${entry.author}.` : "";
  return {
    licence,
    text:
      `This package ships no licence file. Its package.json declares ${licence}, ` +
      `whose standard text follows.${holder}\n\n${normaliseText(stock)}`,
    fallback: true,
    note,
  };
};

const licenceSortKey = (id) => id.replace(/[()]/g, "");

/**
 * Packages grouped by licence id, and within a licence by identical text, so a
 * text shared by fifty packages is printed once beneath all fifty names.
 * Groups sort by licence id; blocks by their first package.
 */
export const groupByLicence = (resolved) => {
  const byLicence = new Map();
  for (const { entry, notice } of resolved) {
    if (!byLicence.has(notice.licence)) byLicence.set(notice.licence, new Map());
    const blocks = byLicence.get(notice.licence);
    const key = `${notice.note ?? ""}\u0000${notice.text}`;
    if (!blocks.has(key)) {
      blocks.set(key, {
        text: notice.text,
        note: notice.note,
        fallback: notice.fallback,
        packages: [],
      });
    }
    blocks.get(key).packages.push(entry);
  }
  return [...byLicence.entries()]
    .sort(([a], [b]) =>
      licenceSortKey(a).localeCompare(licenceSortKey(b), undefined, { sensitivity: "base" })
    )
    .map(([licence, blocks]) => ({
      licence,
      packages: [...blocks.values()].reduce((n, block) => n + block.packages.length, 0),
      blocks: [...blocks.values()]
        .map((block) => ({ ...block, packages: block.packages.sort(comparePackages) }))
        .sort((a, b) => comparePackages(a.packages[0], b.packages[0])),
    }));
};

/**
 * The stock text for an SPDX id or a simple expression of them ("MIT AND ISC",
 * "(MIT OR Apache-2.0)"): every id's text, each under its name. Null when any
 * one is missing.
 */
export const standardTextFor = (expression, readText) => {
  const ids = expression
    .replace(/[()]/g, " ")
    .split(/\s+(?:AND|OR)\s+/)
    .map((id) => id.trim())
    .filter(Boolean);
  const texts = ids.map(readText);
  if (ids.length === 0 || texts.some((text) => !text)) return null;
  if (ids.length === 1) return texts[0];
  return ids.map((id, i) => `[${id}]\n\n${normaliseText(texts[i])}`).join("\n\n");
};

// --- Native code -------------------------------------------------------------

/**
 * The Capacitor plug-ins package.json brings in must each have an entry in
 * native.json, and native.json must name nothing that is gone; every library
 * an entry points at must exist.
 */
export const checkNativeCoverage = (pluginNames, native) => {
  const listed = new Set(Object.keys(native.plugins));
  const problems = [];
  for (const name of pluginNames) {
    if (!listed.has(name))
      problems.push(`${name} is a Capacitor plug-in with no entry in "plugins"`);
  }
  for (const name of listed) {
    if (!pluginNames.includes(name)) {
      problems.push(`"plugins" lists ${name}, which package.json no longer installs`);
    }
  }
  const consumers = { app: native.app, ...native.plugins };
  for (const [consumer, platforms] of Object.entries(consumers)) {
    for (const ids of Object.values(platforms ?? {})) {
      if (!Array.isArray(ids)) continue;
      for (const id of ids) {
        if (!native.libraries[id])
          problems.push(`${consumer} names "${id}", which "libraries" lacks`);
      }
    }
  }
  if (problems.length > 0) {
    throw new Error(
      `third-party-notices: licences/native.json is out of date with package.json:\n  - ${problems.join("\n  - ")}`
    );
  }
};

// The Capacitor platform packages carry native code without being plug-ins.
const CAPACITOR_PLATFORMS = ["@capacitor/android", "@capacitor/ios"];

const nativePluginNames = (packages, rootDir) => {
  const direct = new Set(Object.keys(readJson(join(rootDir, "package.json")).dependencies ?? {}));
  return packages
    .filter(
      (p) => direct.has(p.name) && (p.capacitorPlugin || CAPACITOR_PLATFORMS.includes(p.name))
    )
    .map((p) => p.name)
    .sort();
};

// --- Rendering ---------------------------------------------------------------

const heading = (text) => `${RULE}\n${text}\n${RULE}`;
const subheading = (text) => `${THIN_RULE}\n${text}\n${THIN_RULE}`;
const packageLine = (p) => `  * ${p.name} ${p.version}${p.source ? ` <${p.source}>` : ""}`;

const renderJs = (groups) => {
  const out = [];
  for (const group of groups) {
    out.push(
      subheading(`${group.licence} (${group.packages} package${group.packages === 1 ? "" : "s"})`)
    );
    for (const block of group.blocks) {
      out.push(block.packages.map(packageLine).join("\n"));
      if (block.note) out.push(block.note);
      out.push(block.text);
      out.push("");
    }
  }
  return out.join("\n\n");
};

const renderLibrary = (library, readLicenceFile) => {
  const lines = [`${library.name} (${library.platform})`];
  lines.push(`Version: ${library.version}`);
  if (library.source) lines.push(`Source: ${library.source}`);
  lines.push(`Licence: ${library.licence}`);
  if (library.terms) lines.push(`Terms: ${library.terms}`);
  const body = [lines.join("\n")];
  if (library.note) body.push(library.note);
  if (library.copyright) body.push(library.copyright);
  if (library.notice) body.push(normaliseText(readLicenceFile(library.notice)));
  if (library.licenceFile) {
    body.push(normaliseText(readLicenceFile(library.licenceFile)));
  } else if (!library.terms) {
    body.push(`The full ${library.licence} text is in "${STANDARD_TEXTS_TITLE}" below.`);
  }
  return body.join("\n\n");
};

const STANDARD_TEXTS_TITLE = "5. Standard licence texts";

const renderNative = (native, pluginPackages, readLicenceFile) => {
  const out = [];
  out.push(subheading("Capacitor plug-ins and platforms"));
  out.push(
    "These are npm packages with native code; their licence texts are in part 1. " +
      "Each lists the native libraries it brings into the apps."
  );
  // The short name: "OkHttp", not "OkHttp (com.squareup.okhttp3:okhttp)".
  const libs = (ids) =>
    (ids ?? []).map((id) => native.libraries[id].name.replace(/ \(.*$/, "")).join(", ") || "none";
  for (const p of pluginPackages) {
    const entry = native.plugins[p.name];
    out.push(
      `  * ${p.name} ${p.version} (${p.licence})\n` +
        `      iOS: ${libs(entry.ios)}\n      Android: ${libs(entry.android)}`
    );
  }
  out.push(
    `  * The app itself\n      iOS: ${libs(native.app.ios)}\n      Android: ${libs(native.app.android)}`
  );
  out.push(subheading("Native libraries"));
  const libraries = Object.values(native.libraries).sort(
    (a, b) => a.platform.localeCompare(b.platform) || a.name.localeCompare(b.name)
  );
  for (const library of libraries) {
    out.push(renderLibrary(library, readLicenceFile));
    out.push("");
  }
  return out.join("\n\n");
};

const renderFonts = (fonts, readLicenceFile, readPackageFile) => {
  const out = [];
  for (const font of [...fonts].sort((a, b) => a.name.localeCompare(b.name))) {
    const lines = [font.name, `Shipped by: ${font.shippedBy}`, `Licence: ${font.licence}`];
    if (font.source) lines.push(`Source: ${font.source}`);
    const body = [lines.join("\n")];
    if (font.copyright) body.push(font.copyright);
    if (font.packageLicence) {
      body.push(
        normaliseText(readPackageFile(font.packageLicence.package, font.packageLicence.file))
      );
    } else if (font.licenceFile) {
      body.push(normaliseText(readLicenceFile(font.licenceFile)));
    } else {
      body.push(`The full ${font.licence} text is in "${STANDARD_TEXTS_TITLE}" below.`);
    }
    out.push(body.join("\n\n"));
    out.push("");
  }
  return out.join("\n\n");
};

/**
 * The whole document. `bundleFiles`, when given, is the list of files the
 * build emits, checked against fonts.json.
 */
export const buildNotices = ({ frontendDir = FRONTEND_DIR, bundleFiles = null } = {}) => {
  const licencesDir = join(frontendDir, "licences");
  const { packages: overrides, buildOnly } = readJson(join(licencesDir, "overrides.json"));
  const native = readJson(join(licencesDir, "native.json"));
  const fonts = readJson(join(licencesDir, "fonts.json")).fonts;
  const textsDir = join(licencesDir, "texts");
  const standardText = (expression) =>
    standardTextFor(expression, (id) => {
      const file = join(textsDir, `${id}.txt`);
      return existsSync(file) ? readFileSync(file, "utf-8") : null;
    });
  const readLicenceFile = (relative) => readFileSync(join(licencesDir, relative), "utf-8");

  // 1. JavaScript packages
  const packages = collectPackages(frontendDir, { buildOnly });
  const resolved = packages.map((entry) => ({
    entry,
    notice: resolveNotice(entry, {
      overrides,
      listFiles: findLicenceFiles,
      readFile: (dir, name) => readFileSync(join(dir, name), "utf-8"),
      standardText,
    }),
  }));
  const groups = groupByLicence(resolved);

  // 2. Native code
  const pluginNames = nativePluginNames(packages, frontendDir);
  checkNativeCoverage(pluginNames, native);
  const pluginPackages = pluginNames.map((name) => packages.find((p) => p.name === name));

  // 3. Fonts
  if (bundleFiles) {
    const fontFiles = bundleFiles.filter((f) => /\.(woff2?|ttf|otf|eot)$/i.test(f));
    const unclaimed = fontFiles.filter(
      (f) => !fonts.some((font) => font.files.some((pattern) => new RegExp(pattern).test(f)))
    );
    if (unclaimed.length > 0) {
      throw new Error(
        `third-party-notices: the build emits fonts that licences/fonts.json does not list:\n  - ${unclaimed.join("\n  - ")}`
      );
    }
  }
  const packageDir = (name) => packages.find((p) => p.name === name)?.dir;
  const readPackageFile = (name, file) => {
    const dir = packageDir(name);
    if (!dir)
      throw new Error(`third-party-notices: fonts.json names ${name}, which is not installed`);
    return readFileSync(join(dir, file), "utf-8");
  };

  // 4. Artwork
  const noticeFile = resolve(frontendDir, "..", "NOTICE.md");
  if (!existsSync(noticeFile)) {
    throw new Error(
      `third-party-notices: ${noticeFile} is missing; the artwork credits in it ship with the app`
    );
  }
  const artwork = normaliseText(readFileSync(noticeFile, "utf-8"));

  // 5. Standard texts the native and font entries point at
  const standardIds = [
    ...new Set(
      [...Object.values(native.libraries), ...fonts]
        .filter((item) => !item.licenceFile && !item.packageLicence && !item.terms)
        .map((item) => item.licence)
    ),
  ].sort();
  const standardSection = standardIds
    .map((id) => {
      const text = standardText(id);
      if (!text) throw new Error(`third-party-notices: licences/texts/${id}.txt is missing`);
      return `${subheading(id)}\n\n${normaliseText(text)}\n`;
    })
    .join("\n\n");

  const counts = {
    packages: packages.length,
    licences: groups.length,
    fallbacks: resolved.filter((r) => r.notice.fallback).length,
    plugins: pluginPackages.length,
    nativeLibraries: Object.keys(native.libraries).length,
    fonts: fonts.length,
  };

  const text = [
    HEADER,
    "",
    OWN_LICENCE,
    "",
    "Contents",
    `  1. JavaScript packages (${counts.packages})`,
    `  2. Native code in the iOS and Android apps (${counts.plugins} Capacitor packages, ${counts.nativeLibraries} libraries)`,
    `  3. Fonts (${counts.fonts})`,
    "  4. Artwork",
    `  ${STANDARD_TEXTS_TITLE}`,
    "",
    heading(`1. JavaScript packages (${counts.packages})`),
    "",
    renderJs(groups),
    heading("2. Native code in the iOS and Android apps"),
    "",
    renderNative(native, pluginPackages, readLicenceFile),
    heading("3. Fonts"),
    "",
    renderFonts(fonts, readLicenceFile, readPackageFile),
    heading("4. Artwork"),
    "",
    artwork,
    "",
    heading(STANDARD_TEXTS_TITLE),
    "",
    standardSection,
  ]
    .join("\n")
    .replace(/\n{4,}/g, "\n\n\n");

  return { text: `${text.trimEnd()}\n`, counts };
};

// Run directly: write the file and say what is in it.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = process.argv[2] ?? join(FRONTEND_DIR, "dist", "THIRD_PARTY_NOTICES.txt");
  const { text, counts } = buildNotices();
  writeFileSync(out, text);
  console.log(`third-party-notices: wrote ${out} (${text.length} bytes)`, counts);
}
