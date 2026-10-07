// The rules behind THIRD_PARTY_NOTICES.txt, and one run of the real thing.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildNotices,
  checkNativeCoverage,
  classifyComponent,
  declaredLicence,
  extractCopyrights,
  groupComponents,
  HEADER,
  isStandardText,
  renderComponentLine,
  resolveNotice,
  standardTextFor,
} from "./third-party-notices.mjs";

// The real canonical texts, so detection is tested against what it compares.
const TEXTS = join(import.meta.dirname, "../licences/texts");
const canonicalFor = (id) => {
  try {
    return readFileSync(join(TEXTS, `${id}.txt`), "utf-8");
  } catch {
    return null;
  }
};

const MIT_BODY = `Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;

const mit = (copyright) => `The MIT License (MIT)\n\n${copyright}\n\n${MIT_BODY}\n`;

const pkg = (name, version, licence, extra = {}) => ({
  name,
  version,
  licence,
  author: null,
  source: `https://github.com/example/${name}`,
  dir: `/nm/${name}`,
  ...extra,
});

const files = {
  "/nm/a": { LICENSE: mit("Copyright (c) 2020 Ada") },
  "/nm/c": { LICENSE: canonicalFor("Apache-2.0"), NOTICE: "c\nCopyright 2021 The C Authors" },
  "/nm/d": {},
  "/nm/dual": { LICENSE: "Apache half", "LICENSE-MPL": "MPL half" },
};

const deps = (overrides = {}) => ({
  overrides,
  listFiles: (dir) => Object.keys(files[dir] ?? {}),
  readFile: (dir, name) => files[dir][name],
});

describe("declaredLicence", () => {
  it("reads every shape package.json has used", () => {
    expect(declaredLicence({ license: "MIT" })).toBe("MIT");
    expect(declaredLicence({ license: { type: "ISC" } })).toBe("ISC");
    expect(declaredLicence({ licenses: [{ type: "MIT" }, { type: "Apache-2.0" }] })).toBe(
      "(MIT OR Apache-2.0)"
    );
    expect(declaredLicence({})).toBeNull();
  });
});

describe("extractCopyrights", () => {
  it("takes every notice, as written, and leaves the terms alone", () => {
    const text = [
      "MIT License Copyright (c) 2025 Alexis <alexis@example.com>",
      "# Copyright (c) 2014-present Matt & Collaborators",
      "© 2019 Someone Else",
      "Copyright (c) 2014",
      "  - Kevin <kevin@example.com>",
      "",
      "The above copyright notice and this permission notice shall be included.",
      "      copyright owner or entity authorized by the copyright owner",
    ].join("\n");
    expect(extractCopyrights(text)).toEqual([
      "Copyright (c) 2025 Alexis <alexis@example.com>",
      "Copyright (c) 2014-present Matt & Collaborators",
      "© 2019 Someone Else",
      "Copyright (c) 2014 - Kevin <kevin@example.com>",
    ]);
  });

  it("leaves out a canonical text's blanks", () => {
    expect(extractCopyrights(canonicalFor("MIT"))).toEqual([]);
    expect(extractCopyrights(canonicalFor("Apache-2.0"))).toEqual([]);
  });
});

describe("isStandardText", () => {
  it("knows a standard copy through a title, layout and its own copyright", () => {
    expect(isStandardText("MIT", mit("Copyright (c) 2020 Ada"), canonicalFor)).toBe(true);
    expect(isStandardText("MIT", MIT_BODY, canonicalFor)).toBe(true);
  });

  it("knows an Apache copy with or without the appendix", () => {
    const apache = canonicalFor("Apache-2.0");
    expect(isStandardText("Apache-2.0", apache, canonicalFor)).toBe(true);
    const terms = apache.slice(0, apache.indexOf("END OF TERMS AND CONDITIONS") + 27);
    expect(isStandardText("Apache-2.0", terms, canonicalFor)).toBe(true);
    expect(isStandardText("Apache-2.0", `${terms}\n\nPlus our own clause.`, canonicalFor)).toBe(
      false
    );
  });

  it("keeps anything that differs: a modified MIT, a named BSD clause", () => {
    const modified = mit("Copyright (c) 2020 Ada").replace(
      "this permission notice shall",
      "this permission notice (including the next paragraph) shall"
    );
    expect(isStandardText("MIT", modified, canonicalFor)).toBe(false);
    expect(
      isStandardText("MIT", `${mit("Copyright Ada")}\nThis product bundles X.`, canonicalFor)
    ).toBe(false);
    const named = canonicalFor("BSD-3-Clause").replace(
      "the name of the copyright holder nor the names of its contributors",
      "the name of the author nor the names of contributors"
    );
    expect(isStandardText("BSD-3-Clause", named, canonicalFor)).toBe(false);
  });

  it("does not guess at a licence it has no text for", () => {
    expect(isStandardText("WTFPL", MIT_BODY, canonicalFor)).toBe(false);
  });
});

describe("classifyComponent", () => {
  const classify = (entry, overrides) =>
    classifyComponent(resolveNotice(entry, deps(overrides)), canonicalFor);

  it("puts a standard copy under its licence, with its own copyright", () => {
    const c = classify(pkg("a", "1.0.0", "MIT", { dir: "/nm/a" }));
    expect(c.section).toBe("standard");
    expect(c.copyrights).toEqual(["Copyright (c) 2020 Ada"]);
    expect(renderComponentLine(c)).toBe("  * a 1.0.0 — Copyright (c) 2020 Ada");
  });

  it("keeps an Apache package's NOTICE verbatim under its line", () => {
    const c = classify(pkg("c", "2.0.0", "Apache-2.0", { dir: "/nm/c" }));
    expect(c.section).toBe("standard");
    const line = renderComponentLine(c);
    expect(line).toContain("(no copyright line in the package) https://github.com/example/c");
    expect(line).toContain("[NOTICE]\n      c\n      Copyright 2021 The C Authors");
  });

  it("supplies the standard text for a package that ships none, and says so", () => {
    const c = classify(pkg("d", "1.0.0", "MIT", { dir: "/nm/d", author: "Dee" }));
    expect(c.section).toBe("standard");
    expect(c.supplied).toBe(true);
    const line = renderComponentLine(c);
    expect(line).toContain("(no licence file in the package; the standard text is supplied)");
    expect(line).toContain("author: Dee");
  });

  it("supplies every text of a compound licence in full", () => {
    const c = classify(pkg("d", "1.0.0", "MIT AND ISC", { dir: "/nm/d" }));
    expect(c.section).toBe("other");
    expect(c.text).toContain("[MIT]");
    expect(c.text).toContain("[ISC]");
  });

  it("fails rather than ship a package with no text at all", () => {
    expect(() => classify(pkg("d", "1.0.0", "WTFPL", { dir: "/nm/d" }))).toThrow(
      /ships no licence file/
    );
  });

  it("takes a dual licence's chosen side from the overrides", () => {
    const c = classify(pkg("dual", "3.0.0", "(MPL-2.0 OR Apache-2.0)", { dir: "/nm/dual" }), {
      dual: { licence: "Apache-2.0", files: ["LICENSE"], note: "We take Apache-2.0." },
    });
    expect(c.licence).toBe("Apache-2.0");
    expect(c.section).toBe("other");
    expect(c.text).toBe("Apache half");
  });

  it("says where a copyleft component's source is", () => {
    const c = classifyComponent(
      {
        kind: "package",
        name: "updater",
        version: "8.0.0",
        licence: "MPL-2.0",
        source: "https://github.com/example/updater",
        licenceText: `Copyright 2020 Updater Ltd\n\n${canonicalFor("MPL-2.0")}`,
        attachments: [],
      },
      canonicalFor
    );
    expect(c.section).toBe("standard");
    expect(renderComponentLine(c)).toBe(
      "  * updater 8.0.0 — Copyright 2020 Updater Ltd\n      Source: https://github.com/example/updater"
    );
  });

  it("needs a licence id when a package declares none", () => {
    expect(() => classify(pkg("a", "1.0.0", null, { dir: "/nm/a" }))).toThrow(
      /declares no licence/
    );
  });
});

describe("groupComponents", () => {
  it("makes one group per standard licence, and puts identical other texts together", () => {
    const component = (name, licence, section, text) => ({
      kind: "package",
      name,
      version: "1.0.0",
      licence,
      section,
      text,
    });
    const groups = groupComponents([
      component("b", "MIT", "standard"),
      component("z", "Apache-2.0", "standard"),
      component("a", "MIT", "standard"),
      component("y", "MIT", "other", "Modified"),
      component("x", "MIT", "other", "Modified"),
    ]);
    expect(groups.standard.map((g) => g.licence)).toEqual(["Apache-2.0", "MIT"]);
    expect(groups.standard[1].components.map((c) => c.name)).toEqual(["a", "b"]);
    expect(groups.other).toHaveLength(1);
    expect(groups.other[0].components.map((c) => c.name)).toEqual(["x", "y"]);
  });
});

describe("standardTextFor", () => {
  it("joins the texts of a compound expression, and gives up on a missing one", () => {
    const read = (id) => ({ MIT: "Standard MIT", ISC: "Standard ISC" })[id] ?? null;
    expect(standardTextFor("MIT", read)).toBe("Standard MIT");
    expect(standardTextFor("(MIT AND ISC)", read)).toBe(
      "[MIT]\n\nStandard MIT\n\n[ISC]\n\nStandard ISC"
    );
    expect(standardTextFor("MIT OR WTFPL", read)).toBeNull();
  });
});

describe("checkNativeCoverage", () => {
  const native = {
    app: { android: ["okhttp"] },
    plugins: { "@capacitor/camera": { ios: [], android: ["okhttp"] } },
    libraries: { okhttp: { name: "OkHttp" } },
  };

  it("passes when every plug-in and library is accounted for", () => {
    expect(() => checkNativeCoverage(["@capacitor/camera"], native)).not.toThrow();
  });

  it("fails on a plug-in native.json does not list", () => {
    expect(() =>
      checkNativeCoverage(["@capacitor/camera", "@capacitor/geolocation"], native)
    ).toThrow(/@capacitor\/geolocation is a Capacitor plug-in with no entry/);
  });

  it("fails on a plug-in that is gone, and on a library nobody defined", () => {
    expect(() =>
      checkNativeCoverage([], {
        ...native,
        app: { android: ["guava"] },
      })
    ).toThrow(/no longer installs[\s\S]*"guava"/);
  });
});

describe("buildNotices", () => {
  it("covers this repository's packages, native code, fonts and artwork", () => {
    const { text, counts } = buildNotices({
      bundleFiles: ["assets/outfit-latin-wght-normal-abc.woff2", "assets/Assistant-Bold-def.woff2"],
    });
    expect(text.startsWith(HEADER)).toBe(true);
    expect(text).toContain("https://github.com/beyonders-studio/initiative");
    // Under Apache-2.0's one text, not MPL-2.0's.
    const apache = text.slice(text.indexOf("\nApache-2.0 ("), text.indexOf("\nBSD-3-Clause ("));
    expect(apache).toMatch(/\n {2}\* dompurify [\d.]+ — /);
    expect(text).toMatch(/\n {2}\* elkjs [\d.]+\n {6}Source: https:\/\/github\.com\/kieler\/elkjs/);
    expect(text).toMatch(
      /\n {2}\* @capgo\/capacitor-updater [\d.]+ — .*https:\/\/github\.com\/Cap-go\/capacitor-updater/
    );
    expect(text).toMatch(/\n {2}\* Alamofire, iOS, .* — Copyright/);
    expect(text).toMatch(
      /\n {2}\* OkHttp \(com\.squareup\.okhttp3:okhttp\), Android, .* — Copyright/
    );
    expect(text).toMatch(
      /\n {2}\* Outfit, shipped by .* — Copyright 2021 The Outfit Project Authors/
    );
    expect(text).toContain("# Third-party artwork");
    // The MIT permission text appears once for the group, plus once per MIT
    // text that differs and is printed in full.
    expect(text.split("Permission is hereby granted, free of charge").length - 1).toBeLessThan(
      counts.other + 2
    );
    expect(counts.plugins).toBeGreaterThan(0);
  });

  it("fails when the build emits a font nobody listed", () => {
    expect(() => buildNotices({ bundleFiles: ["assets/Virgil-abc.woff2"] })).toThrow(
      /fonts that licences\/fonts.json does not list/
    );
  });
});
