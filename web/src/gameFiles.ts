export const GAME_SAVE_NAME = "GridironCustomPlays.sav";
export const GAME_BACKUP_DIRECTORY = "GridironPlaybookBackups";
const MAX_SAVE_BYTES = 64 * 1024 * 1024;
const ARCHIVE_PATTERN = /^(\d{16})_([0-9a-f-]{36})\.json$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const INSTALL_LOCK = "gridiron.game-save-write";

export interface GameWritable {
  write(data: Uint8Array<ArrayBuffer> | string): Promise<void>;
  close(): Promise<void>;
  abort(reason?: unknown): Promise<void>;
}

export interface GameFile {
  readonly kind: "file";
  readonly name: string;
  getFile(): Promise<File>;
  createWritable(options?: { keepExistingData?: boolean }): Promise<GameWritable>;
}

export interface GameDirectory {
  readonly kind: "directory";
  readonly name: string;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<GameFile>;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<GameDirectory>;
  entries(): AsyncIterableIterator<[string, GameFile | GameDirectory]>;
}

interface DirectoryPickerWindow extends Window {
  showDirectoryPicker?: (options: { id: string; mode: "readwrite" }) => Promise<GameDirectory>;
}

export type GameFileErrorCode =
  | "unsupported"
  | "cancelled"
  | "unavailable"
  | "changed"
  | "busy"
  | "no-backup"
  | "corrupt-backup"
  | "backup-write"
  | "replacement"
  | "invalid-save";

export class GameFileError extends Error {
  constructor(
    readonly code: GameFileErrorCode,
    message: string,
    readonly backupName: string | null = null,
    options?: ErrorOptions
  ) {
    super(message, options);
    this.name = "GameFileError";
  }
}

export interface GameChangeResult {
  readonly targetName: string;
  readonly backupName: string | null;
  readonly changed: boolean;
}

export interface PreparedGameChange {
  readonly targetName: string;
  readonly restoreBackupName: string | null;
  readonly restoreCreatedAt: string | null;
  readonly changed: boolean;
  apply(): Promise<GameChangeResult>;
}

interface BackupRecord {
  readonly version: 1;
  readonly target: typeof GAME_SAVE_NAME;
  readonly sequence: number;
  readonly createdAt: string;
  readonly digest: string;
  readonly size: number;
}

interface ArchivedBackup {
  readonly filename: string;
  readonly record: BackupRecord;
}

function isNotFound(error: unknown): boolean {
  return error instanceof DOMException && error.name === "NotFoundError";
}

export function supportsGameFiles(): boolean {
  return typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function" && Boolean(navigator.locks);
}

export async function selectGameDirectory(): Promise<GameDirectory> {
  const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
  if (!picker || !navigator.locks) {
    throw new GameFileError(
      "unsupported",
      "This browser cannot install game saves directly. Download the .sav file instead."
    );
  }
  try {
    const directory = await picker.call(window, { id: "gridiron-save-games", mode: "readwrite" });
    await readGameSave(directory);
    return directory;
  } catch (error) {
    if (error instanceof GameFileError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new GameFileError("cancelled", "Folder selection was cancelled.");
    }
    throw new GameFileError(
      "unavailable",
      "Choose the SaveGames folder containing GridironCustomPlays.sav and allow file access.",
      null,
      { cause: error }
    );
  }
}

async function digest(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const result = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(result, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function readBytes(file: GameFile): Promise<Uint8Array<ArrayBuffer>> {
  const contents = await file.getFile();
  if (contents.size > MAX_SAVE_BYTES) {
    throw new GameFileError("invalid-save", "The game-save size limit is 64 MiB.");
  }
  return new Uint8Array(await contents.arrayBuffer());
}

async function readGameSave(directory: GameDirectory): Promise<Uint8Array<ArrayBuffer>> {
  try {
    return await readBytes(await directory.getFileHandle(GAME_SAVE_NAME));
  } catch (error) {
    if (error instanceof GameFileError) throw error;
    throw new GameFileError(
      "unavailable",
      `Could not read ${directory.name}/${GAME_SAVE_NAME}. Keep the game closed and check folder access.`,
      null,
      { cause: error }
    );
  }
}

function backupRecord(value: unknown, sequence: number): BackupRecord {
  const invalid = (): never => {
    throw new GameFileError("corrupt-backup", "A game-save backup record is corrupt. The game save was not replaced.");
  };
  if (typeof value !== "object" || value === null) return invalid();
  const record = value as Record<string, unknown>;
  if (
    record.version !== 1 ||
    record.target !== GAME_SAVE_NAME ||
    record.sequence !== sequence ||
    typeof record.createdAt !== "string" ||
    !Number.isFinite(Date.parse(record.createdAt)) ||
    typeof record.digest !== "string" ||
    !DIGEST_PATTERN.test(record.digest) ||
    typeof record.size !== "number" ||
    !Number.isSafeInteger(record.size) ||
    record.size < 0 ||
    record.size > MAX_SAVE_BYTES
  )
    return invalid();
  if (new Date(record.createdAt).toISOString() !== record.createdAt) return invalid();
  return {
    version: 1,
    target: GAME_SAVE_NAME,
    sequence,
    createdAt: record.createdAt,
    digest: record.digest,
    size: record.size,
  };
}

async function archiveDirectory(directory: GameDirectory, create: boolean): Promise<GameDirectory | null> {
  try {
    return await directory.getDirectoryHandle(GAME_BACKUP_DIRECTORY, { create });
  } catch (error) {
    if (!create && isNotFound(error)) return null;
    throw new GameFileError(
      create ? "backup-write" : "corrupt-backup",
      "The game-save backup folder is unavailable. The game save was not replaced.",
      null,
      { cause: error }
    );
  }
}

async function history(archive: GameDirectory): Promise<ArchivedBackup[]> {
  const result: ArchivedBackup[] = [];
  try {
    for await (const [name, handle] of archive.entries()) {
      const match = ARCHIVE_PATTERN.exec(name);
      if (!match) {
        if (name.endsWith(".json"))
          throw new GameFileError("corrupt-backup", "A game-save backup record has an invalid filename.");
        continue;
      }
      const sequence = Number(match[1]);
      if (!Number.isSafeInteger(sequence) || sequence < 1 || handle.kind !== "file") {
        throw new GameFileError(
          "corrupt-backup",
          "The game-save backup history is corrupt. The game save was not replaced."
        );
      }
      const metadata = await handle.getFile();
      if (metadata.size > 4096) throw new GameFileError("corrupt-backup", "A game-save backup record is too large.");
      const value: unknown = JSON.parse(await metadata.text());
      result.push({ filename: name.slice(0, -5) + ".sav", record: backupRecord(value, sequence) });
    }
    const sequences = new Set(result.map((backup) => backup.record.sequence));
    if (sequences.size !== result.length)
      throw new GameFileError("corrupt-backup", "The game-save backup history has duplicate entries.");
    return result.sort((left, right) => right.record.sequence - left.record.sequence);
  } catch (error) {
    if (error instanceof GameFileError) throw error;
    throw new GameFileError(
      "corrupt-backup",
      "The game-save backup history could not be read. The game save was not replaced.",
      null,
      { cause: error }
    );
  }
}

async function verifiedBackup(archive: GameDirectory, backup: ArchivedBackup): Promise<Uint8Array<ArrayBuffer>> {
  try {
    const bytes = await readBytes(await archive.getFileHandle(backup.filename));
    if (bytes.length !== backup.record.size || (await digest(bytes)) !== backup.record.digest) {
      throw new GameFileError(
        "corrupt-backup",
        `Backup ${backup.filename} failed verification. The game save was not replaced.`
      );
    }
    return bytes;
  } catch (error) {
    if (error instanceof GameFileError && error.code === "corrupt-backup") throw error;
    throw new GameFileError(
      "corrupt-backup",
      `Backup ${backup.filename} is unavailable. The game save was not replaced.`,
      null,
      { cause: error }
    );
  }
}

async function writeAndClose(file: GameFile, data: Uint8Array<ArrayBuffer> | string): Promise<void> {
  const stream = await file.createWritable({ keepExistingData: false });
  try {
    await stream.write(data);
    await stream.close();
  } catch (error) {
    await stream.abort(error).catch(() => undefined);
    throw error;
  }
}

async function createArchiveFile(archive: GameDirectory, name: string): Promise<GameFile> {
  try {
    await archive.getFileHandle(name);
  } catch (error) {
    if (isNotFound(error)) return archive.getFileHandle(name, { create: true });
    throw error;
  }
  throw new GameFileError("backup-write", "A backup filename is already in use. The game save was not replaced.");
}

async function backupCurrent(
  directory: GameDirectory,
  bytes: Uint8Array<ArrayBuffer>,
  expectedDigest: string
): Promise<string> {
  try {
    const archive = await archiveDirectory(directory, true);
    if (!archive) throw new GameFileError("backup-write", "The backup folder could not be created.");
    const records = await history(archive);
    const sequence = (records[0]?.record.sequence ?? 0) + 1;
    if (!Number.isSafeInteger(sequence))
      throw new GameFileError("backup-write", "The backup sequence limit was reached.");
    const stem = `${String(sequence).padStart(16, "0")}_${crypto.randomUUID()}`;
    const filename = `${stem}.sav`;
    const record: BackupRecord = {
      version: 1,
      target: GAME_SAVE_NAME,
      sequence,
      createdAt: new Date().toISOString(),
      digest: expectedDigest,
      size: bytes.length,
    };
    await writeAndClose(await createArchiveFile(archive, filename), bytes);
    await verifiedBackup(archive, { filename, record });
    await writeAndClose(await createArchiveFile(archive, `${stem}.json`), JSON.stringify(record));
    const published = await history(archive);
    const stored = published.find((backup) => backup.filename === filename);
    if (
      !stored ||
      stored.record.digest !== expectedDigest ||
      stored.record.size !== bytes.length ||
      stored.record.createdAt !== record.createdAt
    ) {
      throw new GameFileError("backup-write", "The backup record did not pass verification.");
    }
    await verifiedBackup(archive, stored);
    return `${GAME_BACKUP_DIRECTORY}/${filename}`;
  } catch (error) {
    if (error instanceof GameFileError && error.code === "corrupt-backup") throw error;
    throw new GameFileError(
      "backup-write",
      "A verified backup could not be created. The game save was not replaced.",
      null,
      { cause: error }
    );
  }
}

async function requireUnchanged(directory: GameDirectory, expectedDigest: string): Promise<Uint8Array<ArrayBuffer>> {
  const bytes = await readGameSave(directory);
  if ((await digest(bytes)) !== expectedDigest) {
    throw new GameFileError(
      "changed",
      "The game save changed after confirmation was prepared. Review it again before replacing it."
    );
  }
  return bytes;
}

function preparedChange(
  directory: GameDirectory,
  replacement: Uint8Array<ArrayBuffer>,
  expectedDigest: string,
  replacementDigest: string,
  restored: ArchivedBackup | null
): PreparedGameChange {
  const targetName = `${directory.name}/${GAME_SAVE_NAME}`;
  return Object.freeze({
    targetName,
    restoreBackupName: restored ? `${GAME_BACKUP_DIRECTORY}/${restored.filename}` : null,
    restoreCreatedAt: restored?.record.createdAt ?? null,
    changed: expectedDigest !== replacementDigest,
    async apply(): Promise<GameChangeResult> {
      if (!navigator.locks)
        throw new GameFileError(
          "unsupported",
          "This browser cannot coordinate safe game-save writes. Download the .sav file instead."
        );
      return navigator.locks.request(INSTALL_LOCK, { ifAvailable: true }, async (lock) => {
        if (!lock)
          throw new GameFileError("busy", "Another editor is changing a game save. Try again when it finishes.");
        const current = await requireUnchanged(directory, expectedDigest);
        if (expectedDigest === replacementDigest) return { targetName, backupName: null, changed: false };
        const backupName = await backupCurrent(directory, current, expectedDigest);
        await requireUnchanged(directory, expectedDigest);
        let stream: GameWritable | null = null;
        try {
          const target = await directory.getFileHandle(GAME_SAVE_NAME);
          stream = await target.createWritable({ keepExistingData: false });
          await stream.write(replacement);
          await requireUnchanged(directory, expectedDigest);
          await stream.close();
          stream = null;
          if ((await digest(await readGameSave(directory))) !== replacementDigest) {
            throw new Error("The installed game save failed verification.");
          }
          return { targetName, backupName, changed: true };
        } catch (error) {
          await stream?.abort(error).catch(() => undefined);
          if (error instanceof GameFileError && error.code === "changed") throw error;
          throw new GameFileError(
            "replacement",
            `Could not replace the game save. The previous file is backed up at ${backupName}.`,
            backupName,
            { cause: error }
          );
        }
      });
    },
  });
}

export async function prepareInstall(directory: GameDirectory, bytes: Uint8Array): Promise<PreparedGameChange> {
  if (!bytes.length || bytes.length > MAX_SAVE_BYTES) {
    throw new GameFileError("invalid-save", "Choose a nonempty game save of at most 64 MiB.");
  }
  const replacement = new Uint8Array(bytes);
  const current = await readGameSave(directory);
  return preparedChange(directory, replacement, await digest(current), await digest(replacement), null);
}

export async function prepareRestore(directory: GameDirectory): Promise<PreparedGameChange> {
  const currentDigest = await digest(await readGameSave(directory));
  const archive = await archiveDirectory(directory, false);
  if (archive) {
    for (const backup of await history(archive)) {
      const bytes = await verifiedBackup(archive, backup);
      if (backup.record.digest !== currentDigest) {
        return preparedChange(directory, bytes, currentDigest, backup.record.digest, backup);
      }
    }
  }
  throw new GameFileError("no-backup", "There is no different previous playbook to restore in this folder.");
}
