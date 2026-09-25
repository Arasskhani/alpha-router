/**
 * Unpack a ZIP archive with Node alone, for the extension end-to-end check:
 * the extension is downloaded as the ZIP a person would get and loaded
 * unpacked, as they would. Stored and deflated entries only - what the
 * server writes - and nothing it does not: no encryption, no ZIP64, no path
 * outside the target. Each entry is checked against its size and CRC-32
 * before it is written.
 */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const END_OF_CENTRAL_DIRECTORY = 0x06054b50;
const CENTRAL_FILE_HEADER = 0x02014b50;
const LOCAL_FILE_HEADER = 0x04034b50;
const ENCRYPTED = 0x0001;
const ZIP64_MARK = 0xffffffff;
/** More than any extension build: a bigger entry is not what the server sent. */
const MAX_ENTRY_BYTES = 64 * 1024 * 1024;
const MAX_TOTAL_BYTES = 256 * 1024 * 1024;

function endOfCentralDirectory(zip) {
  // The record is at least 22 bytes and may be followed by a comment of up to 64 KiB.
  for (let at = zip.length - 22; at >= Math.max(0, zip.length - 22 - 0xffff); at -= 1) {
    if (zip.readUInt32LE(at) === END_OF_CENTRAL_DIRECTORY) return at;
  }
  throw new Error("not a ZIP archive");
}

/** Write every file of the archive under `target`; returns the relative paths written. */
export function unzip(zip, target) {
  if (typeof zlib.crc32 !== "function") throw new Error("Node 22.2 or newer is needed to check the ZIP (zlib.crc32)");
  const end = endOfCentralDirectory(zip);
  const count = zip.readUInt16LE(end + 10);
  let at = zip.readUInt32LE(end + 16);
  const root = path.resolve(target);
  const written = [];
  let total = 0;
  for (let i = 0; i < count; i += 1) {
    if (at + 46 > zip.length || zip.readUInt32LE(at) !== CENTRAL_FILE_HEADER) throw new Error("damaged ZIP central directory");
    const flags = zip.readUInt16LE(at + 8);
    const method = zip.readUInt16LE(at + 10);
    const crc = zip.readUInt32LE(at + 16);
    const compressedSize = zip.readUInt32LE(at + 20);
    const size = zip.readUInt32LE(at + 24);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const localOffset = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLength);
    at += 46 + nameLength + extraLength + commentLength;

    if (flags & ENCRYPTED) throw new Error(`encrypted ZIP entry: ${name}`);
    if (compressedSize === ZIP64_MARK || size === ZIP64_MARK || localOffset === ZIP64_MARK) {
      throw new Error(`ZIP64 entry: ${name}`);
    }
    const destination = path.resolve(root, name);
    if (destination !== root && !destination.startsWith(root + path.sep)) throw new Error(`unsafe path in ZIP: ${name}`);
    if (name.endsWith("/")) {
      fs.mkdirSync(destination, { recursive: true });
      continue;
    }
    if (size > MAX_ENTRY_BYTES || (total += size) > MAX_TOTAL_BYTES) throw new Error(`ZIP entry too large: ${name}`);
    if (localOffset + 30 > zip.length || zip.readUInt32LE(localOffset) !== LOCAL_FILE_HEADER) {
      throw new Error(`damaged ZIP entry: ${name}`);
    }
    const dataStart = localOffset + 30 + zip.readUInt16LE(localOffset + 26) + zip.readUInt16LE(localOffset + 28);
    if (dataStart + compressedSize > zip.length) throw new Error(`truncated ZIP entry: ${name}`);
    const data = zip.subarray(dataStart, dataStart + compressedSize);
    let content;
    if (method === 0) content = data;
    // A deflated entry may not inflate past the size the directory gives it.
    else if (method === 8) content = zlib.inflateRawSync(data, { maxOutputLength: Math.max(size, 1) });
    else throw new Error(`unsupported ZIP compression method ${method} for ${name}`);
    if (content.length !== size) throw new Error(`ZIP entry ${name} is ${content.length} bytes, not ${size}`);
    if (zlib.crc32(content) !== crc) throw new Error(`ZIP entry ${name} fails its CRC-32 check`);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, content);
    written.push(name);
  }
  return written;
}
