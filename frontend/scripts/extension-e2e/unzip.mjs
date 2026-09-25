/**
 * Unpack a ZIP archive with Node alone, for the extension end-to-end check:
 * the extension is downloaded as the ZIP a person would get and loaded
 * unpacked, as they would. Stored and deflated entries only - what the
 * server writes.
 */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const END_OF_CENTRAL_DIRECTORY = 0x06054b50;
const CENTRAL_FILE_HEADER = 0x02014b50;
const LOCAL_FILE_HEADER = 0x04034b50;

function endOfCentralDirectory(zip) {
  // The record is at least 22 bytes and may be followed by a comment of up to 64 KiB.
  for (let at = zip.length - 22; at >= Math.max(0, zip.length - 22 - 0xffff); at -= 1) {
    if (zip.readUInt32LE(at) === END_OF_CENTRAL_DIRECTORY) return at;
  }
  throw new Error("not a ZIP archive");
}

/** Write every file of the archive under `target`; returns the relative paths written. */
export function unzip(zip, target) {
  const end = endOfCentralDirectory(zip);
  const count = zip.readUInt16LE(end + 10);
  let at = zip.readUInt32LE(end + 16);
  const root = path.resolve(target);
  const written = [];
  for (let i = 0; i < count; i += 1) {
    if (zip.readUInt32LE(at) !== CENTRAL_FILE_HEADER) throw new Error("damaged ZIP central directory");
    const method = zip.readUInt16LE(at + 10);
    const compressedSize = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const localOffset = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLength);
    at += 46 + nameLength + extraLength + commentLength;

    const destination = path.resolve(root, name);
    if (destination !== root && !destination.startsWith(root + path.sep)) throw new Error(`unsafe path in ZIP: ${name}`);
    if (name.endsWith("/")) {
      fs.mkdirSync(destination, { recursive: true });
      continue;
    }
    if (zip.readUInt32LE(localOffset) !== LOCAL_FILE_HEADER) throw new Error(`damaged ZIP entry: ${name}`);
    const dataStart = localOffset + 30 + zip.readUInt16LE(localOffset + 26) + zip.readUInt16LE(localOffset + 28);
    const data = zip.subarray(dataStart, dataStart + compressedSize);
    let content;
    if (method === 0) content = data;
    else if (method === 8) content = zlib.inflateRawSync(data);
    else throw new Error(`unsupported ZIP compression method ${method} for ${name}`);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, content);
    written.push(name);
  }
  return written;
}
