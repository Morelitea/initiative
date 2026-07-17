/**
 * Client-side backup peek: extract `manifest.json` from a local backup zip
 * WITHOUT uploading (or even fully reading) the file.
 *
 * A zip's central directory lives at the END of the file, so `File.slice()`
 * random access lets us find the manifest entry and inflate just its bytes —
 * a few KB read from a file that may be 256 MB. The result is PREVIEW ONLY:
 * the server re-parses the manifest authoritatively after upload; nothing
 * here is trusted for the actual import.
 *
 * Hand-rolled rather than a zip dependency: we need exactly one member, and
 * `DecompressionStream("deflate-raw")` (baseline in all supported browsers
 * and the Capacitor webview) does the inflate.
 */

// Zip structure signatures.
const EOCD_SIG = 0x06054b50; // end of central directory
const CEN_SIG = 0x02014b50; // central directory file header
const LOC_SIG = 0x04034b50; // local file header

const MANIFEST_NAME = "manifest.json";
// EOCD is 22 bytes + up to 64 KiB of trailing comment.
const EOCD_SEARCH_SPAN = 22 + 65_536;
// A manifest is small; refuse to inflate something absurd.
const MAX_MANIFEST_BYTES = 8 * 1024 * 1024;

/** Why a peek failed, in terms the UI can act on:
 * - ``not_backup`` — the file isn't an Initiative backup (wrong file, wrong
 *   structure, or corrupt beyond recognition).
 * - ``unreadable`` — it looks like a zip we can't decode here (zip64, an
 *   unsupported compression method, a decompression failure).
 * The message is a stable code, never user-facing text — the wizard maps the
 * code to a localized string. */
export type BackupPeekCode = "not_backup" | "unreadable";

export class BackupPeekError extends Error {
  readonly code: BackupPeekCode;
  constructor(code: BackupPeekCode) {
    super(code);
    this.code = code;
    this.name = "BackupPeekError";
  }
}

async function bytes(file: File, start: number, end: number): Promise<DataView> {
  const buf = await file.slice(start, end).arrayBuffer();
  return new DataView(buf);
}

/** Locate the central directory via the end-of-central-directory record. */
async function findCentralDirectory(
  file: File
): Promise<{ offset: number; size: number; count: number }> {
  const tailStart = Math.max(0, file.size - EOCD_SEARCH_SPAN);
  const tail = await bytes(file, tailStart, file.size);
  // Scan backwards for the EOCD signature (comments can contain anything,
  // so take the LAST occurrence).
  for (let i = tail.byteLength - 22; i >= 0; i--) {
    if (tail.getUint32(i, true) === EOCD_SIG) {
      const count = tail.getUint16(i + 10, true);
      const size = tail.getUint32(i + 12, true);
      const offset = tail.getUint32(i + 16, true);
      // 0xffffffff would mean zip64; backups under the 256 MiB cap never are.
      if (offset === 0xffffffff) {
        throw new BackupPeekError("unreadable");
      }
      return { offset, size, count };
    }
  }
  throw new BackupPeekError("not_backup");
}

interface MemberRef {
  compression: number; // 0 = stored, 8 = deflate
  compressedSize: number;
  uncompressedSize: number;
  localHeaderOffset: number;
}

/** Find the manifest's entry in the central directory. */
async function findManifestRef(file: File): Promise<MemberRef> {
  const { offset, size, count } = await findCentralDirectory(file);
  const dir = await bytes(file, offset, Math.min(offset + size, file.size));
  const nameBytes = new TextEncoder().encode(MANIFEST_NAME);
  let pos = 0;
  for (let i = 0; i < count && pos + 46 <= dir.byteLength; i++) {
    if (dir.getUint32(pos, true) !== CEN_SIG) {
      throw new BackupPeekError("not_backup");
    }
    const compression = dir.getUint16(pos + 10, true);
    const compressedSize = dir.getUint32(pos + 20, true);
    const uncompressedSize = dir.getUint32(pos + 24, true);
    const nameLen = dir.getUint16(pos + 28, true);
    const extraLen = dir.getUint16(pos + 30, true);
    const commentLen = dir.getUint16(pos + 32, true);
    const localHeaderOffset = dir.getUint32(pos + 42, true);
    let matches = nameLen === nameBytes.length;
    if (matches) {
      for (let j = 0; j < nameLen; j++) {
        if (dir.getUint8(pos + 46 + j) !== nameBytes[j]) {
          matches = false;
          break;
        }
      }
    }
    if (matches) {
      return { compression, compressedSize, uncompressedSize, localHeaderOffset };
    }
    pos += 46 + nameLen + extraLen + commentLen;
  }
  throw new BackupPeekError("not_backup");
}

async function inflate(compressed: ArrayBuffer, compression: number): Promise<Uint8Array> {
  if (compression === 0) {
    return new Uint8Array(compressed);
  }
  if (compression !== 8) {
    throw new BackupPeekError("unreadable");
  }
  const stream = new Blob([compressed])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  const buf = await new Response(stream).arrayBuffer();
  return new Uint8Array(buf);
}

/** The manifest shape the preview renders — a loose structural type; the
 * server's post-upload plan is the authoritative version. */
export interface PeekedManifest {
  type?: string;
  kind?: string;
  schema_version?: number;
  app_version?: string;
  exported_at?: string;
  guild?: { id?: number; name?: string };
  initiatives?: Array<{ id?: number; name?: string; tools?: Record<string, string> }>;
  entries?: Array<{ tool?: string }>;
  assets?: Array<{ size_bytes?: number }>;
  skipped?: unknown[];
}

/** Read + parse `manifest.json` from a local backup zip. Throws
 * BackupPeekError when the file isn't a readable Initiative backup. */
export async function peekBackupManifest(file: File): Promise<PeekedManifest> {
  const ref = await findManifestRef(file);
  if (ref.uncompressedSize > MAX_MANIFEST_BYTES || ref.compressedSize > MAX_MANIFEST_BYTES) {
    throw new BackupPeekError("not_backup");
  }
  // The local header repeats name/extra with possibly different extra length,
  // so read it to find where the data actually starts.
  const local = await bytes(
    file,
    ref.localHeaderOffset,
    Math.min(ref.localHeaderOffset + 30, file.size)
  );
  if (local.byteLength < 30 || local.getUint32(0, true) !== LOC_SIG) {
    throw new BackupPeekError("not_backup");
  }
  const nameLen = local.getUint16(26, true);
  const extraLen = local.getUint16(28, true);
  const dataStart = ref.localHeaderOffset + 30 + nameLen + extraLen;
  const compressed = await file.slice(dataStart, dataStart + ref.compressedSize).arrayBuffer();
  const inflated = await inflate(compressed, ref.compression);
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(inflated));
  } catch {
    throw new BackupPeekError("not_backup");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new BackupPeekError("not_backup");
  }
  const manifest = parsed as PeekedManifest;
  const discriminator = manifest.type ?? manifest.kind;
  if (discriminator !== "initiative-backup" && discriminator !== "guild-backup") {
    throw new BackupPeekError("not_backup");
  }
  return manifest;
}
