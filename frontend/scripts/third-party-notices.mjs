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
// this collects them again, from three kinds of component:
//
//   - every production JavaScript package installed, read from node_modules
//     with its own LICENSE and NOTICE files;
//   - the native code in the iOS and Android apps, which is not npm packages,
//     so licences/native.json lists it by hand; the build fails when a
//     Capacitor plug-in in package.json is missing from it;
//   - the fonts the build emits, from licences/fonts.json; the build fails
//     when it emits a font file that no entry there claims.
//
// The file is compact. A licence text that is the standard one (compared word
// for word with licences/texts/, ignoring layout, a title and the copyright
// lines) is printed once, and each component under it gets one line with its
// own copyright lines; that is the notice plus the permission text those
// licences ask for. Apache NOTICE files are kept verbatim under their line,
// and copyleft components (MPL, EPL, GPL) say where their source is. Any text
// that differs, by a clause or a name, is printed in full under "Other licence
// texts": when in doubt, the full text. A package with no licence file gets
// the standard text, and its line says so. The artwork credits in the
// repository's NOTICE.md close the file, verbatim.
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

import { collator } from "../src/lib/intl.ts";

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
// ...but not a script that happens to be named for one (cytoscape's
// license-update.mjs).
const CODE_FILE = /\.(?:[cm]?[jt]sx?|json|sh|py)$/i;
const NOTICE_FILE = /^notice([._-].*)?$/i;

/** The licence and notice files at the top of a package, licences first. */
export const findLicenceFiles = (dir) =>
  readdirSync(dir)
    .filter(
      (name) =>
        LICENCE_FILE.test(name) && !CODE_FILE.test(name) && statSync(join(dir, name)).isFile()
    )
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
  a.name.localeCompare(b.name) ||
  collator(undefined, { numeric: true }).compare(a.version, b.version);

// --- Licence texts -----------------------------------------------------------

export const normaliseText = (text) =>
  text
    .replace(/^﻿/, "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .trim();

// A copyright notice starts its line: "Copyright (c) 2020 Foo", "© Bar",
// "(c) 2019 Baz", give or take Markdown ("# Copyright", "**Copyright") or a
// title run onto the same line ("MIT License Copyright (c) ..."). The word
// inside the terms is licence text, not a notice, even when the text wraps to
// put it first ("copyright notice that is included in or attached to the
// work", "copyright owner or entity").
const NOTICE_START =
  /^([ \t]*)[#*>_ \t]*(?:(?:the\s+)?mit\s+licen[cs]e\s+)?((?:copyright\b(?!\s+(?:notices?|owners?|holders?|laws?|and|or|statements?|licen[cs]e|protection|interest|to|of|in|is|the\s+(?:above|following))\b)|©|\(c\)\s*(?:\d|by\b)).*)$/i;
// A notice can run on: indented further, a bulleted list of holders, or a
// bare URL on the next line.
const isContinuation = (line, noticeIndent) => {
  if (!line.trim()) return false;
  if (/^\s*[-*•]\s+\S/.test(line)) return true;
  if (/^\s*<?https?:\/\/\S+>?\s*$/.test(line)) return true;
  return (line.match(/^[ \t]*/)[0].length ?? 0) > noticeIndent;
};
// The blanks in a canonical text, which no package's notice should carry.
const PLACEHOLDER =
  /<year>|<owner>|<copyright holders?>|\[yyyy\]|\[name of copyright owner\]|\bYEAR\b|\bAUTHOR\b/;
const RIGHTS_RESERVED = /^[\s*_]*all rights reserved\.?[\s*_]*$/i;

/** A licence file split into its copyright notices and the terms around them. */
const splitNotices = (text) => {
  const notices = [];
  const body = [];
  let indent = -1;
  for (const line of normaliseText(text).split("\n")) {
    const start = NOTICE_START.exec(line);
    if (start) {
      notices.push(start[2].replace(/[*_\s]+$/, "").trim());
      indent = start[1].length;
      continue;
    }
    if (indent >= 0 && isContinuation(line, indent)) {
      notices[notices.length - 1] += ` ${line.trim()}`;
      continue;
    }
    indent = -1;
    if (RIGHTS_RESERVED.test(line)) continue;
    body.push(line);
  }
  return { notices, body: body.join("\n") };
};

/** Every copyright notice in a licence file, as written, blanks left out. */
export const extractCopyrights = (text) =>
  splitNotices(text).notices.filter((notice) => !PLACEHOLDER.test(notice));

// The words of a licence without its copyright notices, list numbering,
// punctuation or case, so that two copies differing only in layout, quotes,
// http/https or who holds the copyright compare equal.
const licenceWords = (text) =>
  splitNotices(text)
    .body.split("\n")
    .map((line) => line.replace(/^\s*\d+\.\s+/, ""))
    .join("\n")
    .toLowerCase()
    .replace(/\bhttps:/g, "http:")
    .match(/[a-z0-9]+/g)
    ?.join(" ") ?? "";

// A title above the terms ("The MIT License (MIT)", "ISC License") is not part
// of them; copies carry it or not.
const TITLES = [
  /^(?:this software is released under )?(?:the )?mit(?: expat)?(?: licen[cs]e)?(?: mit)? /,
  /^(?:the )?isc licen[cs]e(?: isc)? /,
  /^zlib licen[cs]e /,
  /^bsd (?:2|3|two|three) clause licen[cs]e /,
  /^bsd zero clause licen[cs]e /,
  /^(?:the )?unlicen[cs]e /,
];
// The OFL's own lead-in, as fonts ship it: "This Font Software is licensed
// under the SIL Open Font License, Version 1.1. This license is copied below,
// and is also available with a FAQ at: <url>".
const OFL_LEAD_IN =
  /^this font software is licensed under the sil open font license version 1 1 this license is copied below and is also available with a faq at(?: [a-z0-9]+){1,6}? (?=sil open font license version 1 1 26 february 2007 )/;
// An Apache copy may stop at the end of the terms, or carry the appendix on
// how to apply the licence, or only the boilerplate notice from it.
const APACHE_END = "end of terms and conditions";
const APACHE_BOILERPLATE = "licensed under the apache license";

const comparableWords = (words) => {
  let out = `${words} `.replace(OFL_LEAD_IN, "");
  for (const title of TITLES) out = out.replace(title, "");
  return out.trim();
};

/** A licence as the words standard-text detection compares. */
export const comparableText = (text) => comparableWords(licenceWords(text));

/**
 * Whether `text` is the standard `licence` text, give or take layout, a title
 * and its copyright notices. Anything else (an extra clause, a name in the BSD
 * endorsement clause, a trademark notice, a bundled third party's terms) is
 * not, and keeps its full text.
 */
export const isStandardText = (licence, text, canonicalFor) => {
  const canonical = canonicalFor(licence);
  if (!canonical) return false;
  const pkg = comparableText(text);
  const full = comparableText(canonical);
  if (pkg === full) return true;
  if (licence === "Apache-2.0") {
    const end = full.indexOf(APACHE_END) + APACHE_END.length;
    if (end <= APACHE_END.length || pkg.slice(0, end) !== full.slice(0, end)) return false;
    const rest = pkg.slice(end).trim();
    const boilerplate = full.slice(full.lastIndexOf(APACHE_BOILERPLATE));
    return rest === "" || rest === boilerplate;
  }
  return false;
};

/** A canonical text as printed: its copyright placeholder lines left out. */
const printableCanonical = (text) =>
  normaliseText(text)
    .split("\n")
    .filter((line) => !(NOTICE_START.test(line) && PLACEHOLDER.test(line)))
    .join("\n")
    .trim();

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

// --- Reading a package's licence -----------------------------------------------

/**
 * One package as a component: its licence id, the text of its licence files,
 * and what must be reproduced verbatim beside it (NOTICE files, and any
 * `extraFiles` overrides.json names).
 *
 * `readFile(dir, name)` and `listFiles(dir)` are injected so the rules can be
 * tested without a node_modules.
 */
export const resolveNotice = (entry, { overrides, listFiles, readFile }) => {
  const override = overrides[entry.name] ?? {};
  const licence = override.licence ?? entry.licence;
  const files = override.files ?? listFiles(entry.dir);
  const licenceFiles = files.filter((name) => !NOTICE_FILE.test(name));
  const attachments = [
    ...files.filter((name) => NOTICE_FILE.test(name)),
    ...(override.extraFiles ?? []),
  ].map((name) => ({ name, text: normaliseText(readFile(entry.dir, name)) }));
  if (!licence) {
    throw new Error(
      `third-party-notices: ${entry.name}@${entry.version} declares no licence; ` +
        "name it in licences/overrides.json"
    );
  }
  const texts = licenceFiles.map((name) => normaliseText(readFile(entry.dir, name)));
  return {
    kind: "package",
    name: entry.name,
    version: entry.version,
    licence,
    source: entry.source,
    author: entry.author,
    // Two licence files are only ever compared as the one text they make.
    licenceText:
      texts.length === 0
        ? null
        : texts.length === 1
          ? texts[0]
          : licenceFiles.map((name, i) => `[${name}]\n\n${texts[i]}`).join("\n\n"),
    attachments,
    note: override.note ?? null,
  };
};

// Licences that ask for the source to be pointed at, so every line under one
// says where it is.
const COPYLEFT = /^(?:MPL|EPL|GPL|LGPL|AGPL|CDDL)-/;

/**
 * Where a component goes: under its licence's standard text, with its own
 * copyright lines; in "Other licence texts" with its whole text; or, for a
 * proprietary SDK, to a link to its terms.
 */
export const classifyComponent = (component, canonicalFor) => {
  if (component.terms) return { ...component, section: "proprietary" };
  const { licence, licenceText } = component;
  if (licenceText) {
    if (isStandardText(licence, licenceText, canonicalFor)) {
      const copyrights = component.copyright
        ? [component.copyright, ...extractCopyrights(licenceText)]
        : extractCopyrights(licenceText);
      return { ...component, section: "standard", copyrights: [...new Set(copyrights)] };
    }
    return { ...component, section: "other", text: licenceText };
  }
  // No licence file: the canonical text stands in, and the line says so.
  if (canonicalFor(licence)) {
    return {
      ...component,
      section: "standard",
      copyrights: component.copyright ? [component.copyright] : [],
      supplied: component.kind === "package",
    };
  }
  const stock = standardTextFor(licence, canonicalFor);
  if (!stock) {
    throw new Error(
      `third-party-notices: ${component.name} ${component.version} ships no licence file and ` +
        `licences/texts/ has no standard text for "${licence}"; add one, or an entry in ` +
        "licences/overrides.json"
    );
  }
  return {
    ...component,
    section: "other",
    supplied: true,
    text: `${SUPPLIED}\n\n${normaliseText(stock)}`,
  };
};

const SUPPLIED = "(no licence file in the package; the standard text is supplied)";

const compareComponents = (a, b) =>
  KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) ||
  a.name.localeCompare(b.name) ||
  collator(undefined, { numeric: true }).compare(String(a.version), String(b.version));
const KIND_ORDER = ["package", "native", "font"];

const licenceSortKey = (id) => id.replace(/[()]/g, "");
const byLicence = (a, b) =>
  collator(undefined, { sensitivity: "base" }).compare(licenceSortKey(a), licenceSortKey(b));

/**
 * Classified components in their sections: standard licences grouped by id
 * (one text each), other texts grouped by identical text, proprietary alone.
 */
export const groupComponents = (classified) => {
  const standard = new Map();
  const other = new Map();
  const proprietary = [];
  for (const component of classified) {
    if (component.section === "standard") {
      if (!standard.has(component.licence)) standard.set(component.licence, []);
      standard.get(component.licence).push(component);
    } else if (component.section === "other") {
      const key = `${component.licence}\u0000${component.text}`;
      if (!other.has(key))
        other.set(key, { licence: component.licence, text: component.text, components: [] });
      other.get(key).components.push(component);
    } else {
      proprietary.push(component);
    }
  }
  return {
    standard: [...standard.entries()]
      .sort(([a], [b]) => byLicence(a, b))
      .map(([licence, components]) => ({
        licence,
        components: components.sort(compareComponents),
      })),
    other: [...other.values()]
      .map((block) => ({ ...block, components: block.components.sort(compareComponents) }))
      .sort(
        (a, b) =>
          byLicence(a.licence, b.licence) || compareComponents(a.components[0], b.components[0])
      ),
    proprietary: proprietary.sort(compareComponents),
  };
};

// --- Rendering ---------------------------------------------------------------

const heading = (text) => `${RULE}\n${text}\n${RULE}`;
const subheading = (text) => `${THIN_RULE}\n${text}\n${THIN_RULE}`;
const indent = (text, by = "      ") =>
  text
    .split("\n")
    .map((line) => (line ? `${by}${line}` : ""))
    .join("\n");

const componentName = (c) =>
  c.kind === "package" ? `${c.name} ${c.version}` : `${c.name}, ${c.where}`;

/**
 * One component's line under its licence: `name version — copyright`, then
 * whatever has to go with it (source for copyleft, NOTICE files, a note).
 */
export const renderComponentLine = (c) => {
  const lines = [];
  const copyrights = c.copyrights ?? [];
  let lead;
  if (c.supplied) {
    lead = `${SUPPLIED}${c.author ? ` author: ${c.author}` : ""}`;
  } else if (copyrights.length > 0) {
    lead = copyrights[0];
  } else {
    const who = [c.source, c.author ? `author: ${c.author}` : null].filter(Boolean).join("; ");
    lead = `(no copyright line in the package)${who ? ` ${who}` : ""}`;
  }
  lines.push(`  * ${componentName(c)} — ${lead}`);
  for (const extra of copyrights.slice(c.supplied ? 0 : 1)) lines.push(`      ${extra}`);
  // Named once: the no-copyright lead already carries the repository.
  const sourceShown = !c.supplied && copyrights.length === 0;
  if (c.source && !sourceShown && (COPYLEFT.test(c.licence) || c.supplied)) {
    lines.push(`      Source: ${c.source}`);
  }
  if (c.note) lines.push(indent(c.note));
  for (const attachment of c.attachments ?? []) {
    lines.push(`      [${attachment.name}]`);
    lines.push(indent(attachment.text));
  }
  return lines.join("\n");
};

const KIND_TITLES = {
  package: "JavaScript packages",
  native: "Native libraries in the iOS and Android apps",
  font: "Fonts",
};

const renderByKind = (components, render) =>
  KIND_ORDER.filter((kind) => components.some((c) => c.kind === kind))
    .map(
      (kind) =>
        `${KIND_TITLES[kind]}:\n\n${components
          .filter((c) => c.kind === kind)
          .map(render)
          .join("\n")}`
    )
    .join("\n\n");

const renderStandard = (groups, canonicalFor) =>
  groups
    .map(
      ({ licence, components }) =>
        `${subheading(`${licence} (${components.length})`)}\n\n` +
        `${printableCanonical(canonicalFor(licence))}\n\n` +
        `Each component below is licensed under the ${licence} text above, under its own copyright notice.\n\n` +
        renderByKind(components, renderComponentLine)
    )
    .join("\n\n\n");

const otherLine = (c) => {
  const lines = [`  * ${componentName(c)}`];
  if (c.source) lines.push(`      Source: ${c.source}`);
  if (c.note) lines.push(indent(c.note));
  for (const attachment of c.attachments ?? []) {
    lines.push(`      [${attachment.name}]`);
    lines.push(indent(attachment.text));
  }
  return lines.join("\n");
};

const renderOther = (blocks) =>
  blocks
    .map(
      ({ licence, text, components }) =>
        `${subheading(`${licence}: ${components.map((c) => c.name).join(", ")}`)}\n\n` +
        `${components.map(otherLine).join("\n")}\n\n${text}`
    )
    .join("\n\n\n");

const renderProprietary = (components) =>
  components
    .map((c) =>
      [
        `  * ${componentName(c)}`,
        `      ${c.licence}`,
        `      Terms: ${c.terms}`,
        c.note ? indent(c.note) : null,
      ]
        .filter(Boolean)
        .join("\n")
    )
    .join("\n");

const renderNativeMap = (native, pluginPackages) => {
  // The short name: "OkHttp", not "OkHttp (com.squareup.okhttp3:okhttp)".
  const libs = (ids) =>
    (ids ?? []).map((id) => native.libraries[id].name.replace(/ \(.*$/, "")).join(", ") || "none";
  const lines = pluginPackages.map(
    (p) =>
      `  * ${p.name} ${p.version}\n      iOS: ${libs(native.plugins[p.name].ios)}\n      Android: ${libs(native.plugins[p.name].android)}`
  );
  lines.push(
    `  * The app itself\n      iOS: ${libs(native.app.ios)}\n      Android: ${libs(native.app.android)}`
  );
  return lines.join("\n");
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

// --- The whole document --------------------------------------------------------

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
  const canonicalFor = (id) => {
    const file = join(textsDir, `${id}.txt`);
    return existsSync(file) ? readFileSync(file, "utf-8") : null;
  };
  const readLicenceFile = (relative) =>
    normaliseText(readFileSync(join(licencesDir, relative), "utf-8"));

  // JavaScript packages
  const packages = collectPackages(frontendDir, { buildOnly });
  const components = packages.map((entry) =>
    resolveNotice(entry, {
      overrides,
      listFiles: findLicenceFiles,
      readFile: (dir, name) => readFileSync(join(dir, name), "utf-8"),
    })
  );

  // Native code
  const pluginNames = nativePluginNames(packages, frontendDir);
  checkNativeCoverage(pluginNames, native);
  const pluginPackages = pluginNames.map((name) => packages.find((p) => p.name === name));
  for (const library of Object.values(native.libraries)) {
    components.push({
      kind: "native",
      name: library.name,
      version: library.version,
      where: `${library.platform}, ${library.version}`,
      licence: library.licence,
      source: library.source ?? null,
      copyright: library.copyright ?? null,
      licenceText: library.licenceFile ? readLicenceFile(library.licenceFile) : null,
      attachments: library.notice
        ? [{ name: "NOTICE", text: readLicenceFile(library.notice) }]
        : [],
      terms: library.terms ?? null,
      note: library.note ?? null,
    });
  }

  // Fonts
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
  const readPackageFile = (name, file) => {
    const dir = packages.find((p) => p.name === name)?.dir;
    if (!dir) {
      throw new Error(`third-party-notices: fonts.json names ${name}, which is not installed`);
    }
    return normaliseText(readFileSync(join(dir, file), "utf-8"));
  };
  for (const font of fonts) {
    components.push({
      kind: "font",
      name: font.name,
      version: "",
      where: `shipped by ${font.shippedBy}`,
      licence: font.licence,
      source: font.source ?? null,
      copyright: font.copyright ?? null,
      licenceText: font.packageLicence
        ? readPackageFile(font.packageLicence.package, font.packageLicence.file)
        : font.licenceFile
          ? readLicenceFile(font.licenceFile)
          : null,
      attachments: [],
      note: null,
    });
  }

  // Artwork
  const noticeFile = resolve(frontendDir, "..", "NOTICE.md");
  if (!existsSync(noticeFile)) {
    throw new Error(
      `third-party-notices: ${noticeFile} is missing; the artwork credits in it ship with the app`
    );
  }
  const artwork = normaliseText(readFileSync(noticeFile, "utf-8"));

  const sections = groupComponents(components.map((c) => classifyComponent(c, canonicalFor)));
  const otherCount = sections.other.reduce((n, block) => n + block.components.length, 0);
  const counts = {
    packages: packages.length,
    nativeLibraries: Object.keys(native.libraries).length,
    fonts: fonts.length,
    plugins: pluginPackages.length,
    standardLicences: sections.standard.length,
    standard: sections.standard.reduce((n, group) => n + group.components.length, 0),
    other: otherCount,
    otherPackages: sections.other.reduce(
      (n, block) => n + block.components.filter((c) => c.kind === "package").length,
      0
    ),
    proprietary: sections.proprietary.length,
    supplied: components.filter((c) => c.kind === "package" && !c.licenceText).length,
  };

  const text = [
    HEADER,
    "",
    OWN_LICENCE,
    "",
    `This covers ${counts.packages} JavaScript packages, ${counts.nativeLibraries} native libraries ` +
      `in the iOS and Android apps, ${counts.fonts} fonts, and artwork.`,
    "",
    "Contents",
    `  1. Standard licences (${counts.standard} components under ${counts.standardLicences} licence texts)`,
    `  2. Other licence texts (${counts.other} components)`,
    `  3. Proprietary components in the Android app (${counts.proprietary})`,
    `  4. Which native libraries each Capacitor plug-in brings in (${counts.plugins})`,
    "  5. Artwork",
    "",
    heading("1. Standard licences"),
    "",
    "Each licence text is printed once, followed by every component under it with that component's own copyright notice. NOTICE files, which Apache-2.0 requires verbatim, follow their component.",
    "",
    renderStandard(sections.standard, canonicalFor),
    "",
    heading("2. Other licence texts"),
    "",
    "Components whose licence text differs from the standard one, printed in full.",
    "",
    renderOther(sections.other),
    "",
    heading("3. Proprietary components in the Android app"),
    "",
    renderProprietary(sections.proprietary),
    "",
    heading("4. Which native libraries each Capacitor plug-in brings in"),
    "",
    renderNativeMap(native, pluginPackages),
    "",
    heading("5. Artwork"),
    "",
    artwork,
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
