// The rules behind THIRD_PARTY_NOTICES.txt, and one run of the real thing.
import { describe, expect, it } from "vitest";

import {
  buildNotices,
  checkNativeCoverage,
  declaredLicence,
  groupByLicence,
  HEADER,
  resolveNotice,
  standardTextFor,
} from "./third-party-notices.mjs";

const pkg = (name, version, licence, extra = {}) => ({
  name,
  version,
  licence,
  author: null,
  source: null,
  dir: `/nm/${name}`,
  ...extra,
});

const files = {
  "/nm/a": { LICENSE: "MIT text, Copyright A" },
  "/nm/b": { LICENSE: "MIT text, Copyright A" },
  "/nm/c": { "LICENSE.md": "Apache text", NOTICE: "Notice of c" },
  "/nm/d": {},
  "/nm/dual": { LICENSE: "Apache half", "LICENSE-MPL": "MPL half" },
};

const deps = (overrides = {}) => ({
  overrides,
  listFiles: (dir) => Object.keys(files[dir] ?? {}),
  readFile: (dir, name) => files[dir][name],
  standardText: (expression) =>
    standardTextFor(expression, (id) => ({ MIT: "Standard MIT", ISC: "Standard ISC" })[id] ?? null),
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

describe("resolveNotice", () => {
  it("keeps a package's own files, NOTICE included, verbatim", () => {
    const notice = resolveNotice(pkg("c", "1.0.0", "Apache-2.0", { dir: "/nm/c" }), deps());
    expect(notice.fallback).toBe(false);
    expect(notice.text).toContain("Apache text");
    expect(notice.text).toContain("Notice of c");
  });

  it("falls back to the standard text, and says so, when a package ships none", () => {
    const notice = resolveNotice(
      pkg("d", "1.0.0", "MIT AND ISC", { dir: "/nm/d", author: "Dee" }),
      deps()
    );
    expect(notice.fallback).toBe(true);
    expect(notice.text).toMatch(/^This package ships no licence file/);
    expect(notice.text).toContain("Dee");
    expect(notice.text).toContain("[MIT]\n\nStandard MIT");
    expect(notice.text).toContain("[ISC]\n\nStandard ISC");
  });

  it("fails rather than ship a package with no text at all", () => {
    expect(() => resolveNotice(pkg("d", "1.0.0", "WTFPL", { dir: "/nm/d" }), deps())).toThrow(
      /ships no licence file/
    );
  });

  it("takes a dual licence's chosen side from the overrides", () => {
    const notice = resolveNotice(
      pkg("dual", "3.0.0", "(MPL-2.0 OR Apache-2.0)", { dir: "/nm/dual" }),
      deps({ dual: { licence: "Apache-2.0", files: ["LICENSE"], note: "We take Apache-2.0." } })
    );
    expect(notice.licence).toBe("Apache-2.0");
    expect(notice.text).toBe("Apache half");
    expect(notice.note).toBe("We take Apache-2.0.");
  });

  it("needs a licence id when a package declares none", () => {
    expect(() => resolveNotice(pkg("a", "1.0.0", null, { dir: "/nm/a" }), deps())).toThrow(
      /declares no licence/
    );
  });
});

describe("groupByLicence", () => {
  it("prints a shared text once, under every package that shares it", () => {
    const entries = [
      pkg("b", "2.0.0", "MIT", { dir: "/nm/b" }),
      pkg("c", "1.0.0", "Apache-2.0", { dir: "/nm/c" }),
      pkg("a", "1.0.0", "MIT", { dir: "/nm/a" }),
    ];
    const groups = groupByLicence(
      entries.map((entry) => ({ entry, notice: resolveNotice(entry, deps()) }))
    );
    expect(groups.map((g) => g.licence)).toEqual(["Apache-2.0", "MIT"]);
    const mit = groups[1];
    expect(mit.packages).toBe(2);
    expect(mit.blocks).toHaveLength(1);
    expect(mit.blocks[0].packages.map((p) => p.name)).toEqual(["a", "b"]);
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
    expect(text).toMatch(/\n {2}\* dompurify [\d.]+/);
    expect(text).toContain("Initiative takes it under Apache-2.0.");
    expect(text).toMatch(/EPL-2\.0 \(\d+ packages?\)[\s\S]*\n {2}\* elkjs /);
    expect(text).toMatch(/\* @capgo\/capacitor-updater [\d.]+ \(MPL-2\.0\)/);
    expect(text).toContain("Alamofire (iOS)");
    expect(text).toContain("OkHttp (com.squareup.okhttp3:okhttp) (Android)");
    expect(text).toContain("Outfit\nShipped by:");
    expect(text).toContain("# Third-party artwork");
    expect(counts.plugins).toBeGreaterThan(0);
  });

  it("fails when the build emits a font nobody listed", () => {
    expect(() => buildNotices({ bundleFiles: ["assets/Virgil-abc.woff2"] })).toThrow(
      /fonts that licences\/fonts.json does not list/
    );
  });
});
