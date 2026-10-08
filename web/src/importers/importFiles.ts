/**
 * The import pipeline: unpack ZIPs, enforce limits, detect and parse each file.
 * Every input file gets a result, recognized or rejected with a reason (AC-10.3:
 * no silent drops). Runs inside the import Web Worker; pure enough to test directly.
 */
import {unzipSync} from 'fflate';

import {
  parseFile,
  UnsupportedFileError,
  type Parsed,
  type RejectReason,
} from './formats';

export const MAX_FILE_BYTES = 100 * 1024 * 1024; // plan §15.5
export const MAX_IMPORT_BYTES = 500 * 1024 * 1024;

export interface InputFile {
  name: string;
  size: number;
  bytes: () => Promise<Uint8Array>;
}

export type FileOutcome =
  | {file: string; ok: true; parsed: Parsed}
  | {file: string; ok: false; reason: RejectReason};

export interface Progress {
  done: number;
  total: number;
  current: string;
}

const PARSEABLE = /\.(json|jsonl|csv|tsv|txt)$/i;

function decode(bytes: Uint8Array): string {
  // A UTF-8 byte-order mark (Excel, some exporters) is removed by the parsers' trim().
  return new TextDecoder('utf-8').decode(bytes);
}

function fromZip(
  name: string,
  bytes: Uint8Array,
): {name: string; bytes: Uint8Array}[] {
  // Only listening files are inflated (exports also contain images and docs).
  const entries = unzipSync(bytes, {
    filter: entry =>
      PARSEABLE.test(entry.name) && entry.originalSize <= MAX_FILE_BYTES,
  });
  return Object.entries(entries)
    .filter(
      ([path]) =>
        !path
          .split('/')
          .some(part => part.startsWith('.') || part === '__MACOSX'),
    )
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, data]) => ({name: `${name} › ${path}`, bytes: data}));
}

/**
 * Imports files and returns one outcome per file (ZIP entries count as files).
 *
 * @throws DOMException with name "AbortError" when cancelled.
 */
export async function importFiles(
  files: InputFile[],
  onProgress: (progress: Progress) => void,
  signal?: AbortSignal,
): Promise<FileOutcome[]> {
  const outcomes: FileOutcome[] = [];
  const total = files.reduce((sum, f) => sum + f.size, 0);
  if (total > MAX_IMPORT_BYTES) {
    return files.map(f => ({
      file: f.name,
      ok: false,
      reason: 'importTooLarge' as const,
    }));
  }
  let done = 0;
  for (const file of files) {
    signal?.throwIfAborted();
    onProgress({done, total: files.length, current: file.name});
    if (file.size > MAX_FILE_BYTES) {
      outcomes.push({
        file: file.name,
        ok: false,
        reason: 'tooLarge',
      });
      done++;
      continue;
    }
    const bytes = await file.bytes();
    const units = /\.zip$/i.test(file.name)
      ? safeUnzip(file.name, bytes, outcomes)
      : [{name: file.name, bytes}];
    for (const unit of units) {
      signal?.throwIfAborted();
      try {
        outcomes.push({
          file: unit.name,
          ok: true,
          parsed: parseFile(unit.name, decode(unit.bytes)),
        });
      } catch (error) {
        const reason: RejectReason =
          error instanceof UnsupportedFileError ? error.reason : 'damaged';
        outcomes.push({file: unit.name, ok: false, reason});
      }
    }
    done++;
  }
  onProgress({done, total: files.length, current: ''});
  return outcomes;
}

function safeUnzip(
  name: string,
  bytes: Uint8Array,
  outcomes: FileOutcome[],
): {name: string; bytes: Uint8Array}[] {
  try {
    const units = fromZip(name, bytes);
    if (units.length === 0)
      outcomes.push({
        file: name,
        ok: false,
        reason: 'zipEmpty',
      });
    return units;
  } catch {
    outcomes.push({
      file: name,
      ok: false,
      reason: 'zipDamaged',
    });
    return [];
  }
}
