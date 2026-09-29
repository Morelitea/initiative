// Write the signed statement an app update is installed on.
//
//   node scripts/sign-ota.mjs <ota-dir> <version> <min-native-version> <key-file>
//
// Reads <ota-dir>/bundle.sha256 and writes <ota-dir>/statement.json and
// <ota-dir>/statement.sig: the bundle's version, digest and the oldest app it
// runs on, signed with the ECDSA P-256 key in <key-file> (PKCS#8 PEM). The
// signature is IEEE P1363 (r || s), base64, the form WebCrypto verifies.
// Without a key file nothing is written, and the app installs no update from
// this build.
import { sign } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [dir, version, minNativeVersion, keyFile] = process.argv.slice(2);
if (!keyFile || !existsSync(keyFile) || readFileSync(keyFile, "utf8").trim() === "") {
  console.log("sign-ota: no signing key; this build's bundle is unsigned");
  process.exit(0);
}
const sha256 = readFileSync(join(dir, "bundle.sha256"), "utf8").trim();
const statement = JSON.stringify({ v: 1, version, sha256, minNativeVersion });
const signature = sign("sha256", Buffer.from(statement), {
  key: readFileSync(keyFile, "utf8"),
  dsaEncoding: "ieee-p1363",
}).toString("base64");
writeFileSync(join(dir, "statement.json"), statement);
writeFileSync(join(dir, "statement.sig"), signature);
console.log(`sign-ota: signed ${version}`);
