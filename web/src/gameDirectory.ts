import { GAME_SAVE_NAME, GameFileError, validateGameDirectory } from "./gameFiles";

const DATABASE_NAME = "gridiron-game-directory";
const STORE_NAME = "directories";
const SAVED_DIRECTORY_KEY = "current";
const SAVE_DIRECTORY_PATHS = [[], ["Saved", "SaveGames"], ["Gridiron", "Saved", "SaveGames"]] as const;
export const DEFAULT_WINDOWS_STEAM_FOLDER = "C:\\Program Files (x86)\\Steam\\steamapps\\common";

interface DirectoryPickerWindow extends Window {
  showDirectoryPicker?: (options: {
    id: string;
    mode: "readwrite";
    startIn?: FileSystemDirectoryHandle;
  }) => Promise<FileSystemDirectoryHandle>;
}

function savedDirectory(value: unknown): FileSystemDirectoryHandle | null {
  if (value === undefined) return null;
  if (
    !(value instanceof FileSystemDirectoryHandle) ||
    typeof value.queryPermission !== "function" ||
    typeof value.requestPermission !== "function"
  )
    throw new Error("Invalid saved directory.");
  return value;
}

async function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, 1);
    let rejected = false;
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME);
    request.onblocked = () => {
      rejected = true;
      reject(new Error("The saved folder database is blocked."));
    };
    request.onerror = () => {
      rejected = true;
      reject(request.error);
    };
    request.onsuccess = () => {
      const database = request.result;
      if (rejected) database.close();
      else {
        database.onversionchange = () => database.close();
        resolve(database);
      }
    };
  });
}

async function directoryTransaction<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  let database: IDBDatabase | undefined;
  try {
    database = await openDatabase();
    return await new Promise<T>((resolve, reject) => {
      const transaction = database!.transaction(STORE_NAME, mode);
      const request = operation(transaction.objectStore(STORE_NAME));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = () => reject(transaction.error ?? new Error("The folder could not be remembered."));
      transaction.onerror = () => reject(transaction.error);
    });
  } catch (cause) {
    throw new GameFileError("storage", "The browser could not remember the game folder.", null, { cause });
  } finally {
    database?.close();
  }
}

export async function readSavedGameDirectory(): Promise<FileSystemDirectoryHandle | null> {
  const value = await directoryTransaction<unknown>("readonly", (store) => store.get(SAVED_DIRECTORY_KEY));
  try {
    return savedDirectory(value);
  } catch (cause) {
    throw new GameFileError("storage", "The saved game folder could not be loaded. Choose it again.", null, { cause });
  }
}

export async function rememberGameDirectory(directory: FileSystemDirectoryHandle): Promise<void> {
  await directoryTransaction("readwrite", (store) => store.put(directory, SAVED_DIRECTORY_KEY));
}

export async function forgetGameDirectory(): Promise<void> {
  await directoryTransaction("readwrite", (store) => store.delete(SAVED_DIRECTORY_KEY));
}

export function supportsGameFiles(): boolean {
  return typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function" && Boolean(navigator.locks);
}

export async function hasGameDirectoryAccess(directory: FileSystemDirectoryHandle): Promise<boolean> {
  try {
    return (await directory.queryPermission({ mode: "readwrite" })) === "granted";
  } catch (cause) {
    throw new GameFileError("unavailable", "The saved game folder is unavailable. Choose it again.", null, { cause });
  }
}

export async function reconnectGameDirectory(directory: FileSystemDirectoryHandle): Promise<void> {
  // Request directly from the button click; browser prompts require user activation.
  let permission: PermissionState;
  try {
    permission = await directory.requestPermission({ mode: "readwrite" });
  } catch (cause) {
    throw new GameFileError(
      "unavailable",
      "The browser could not reconnect to the game folder. Try again or choose another folder.",
      null,
      { cause }
    );
  }
  if (permission !== "granted") {
    throw new GameFileError("permission", "Allow folder access or choose another game folder.");
  }
  await validateGameDirectory(directory);
}

export async function resolveGameDirectory(directory: FileSystemDirectoryHandle): Promise<FileSystemDirectoryHandle> {
  for (const segments of SAVE_DIRECTORY_PATHS) {
    let candidate = directory;
    try {
      for (const segment of segments) candidate = await candidate.getDirectoryHandle(segment);
      await candidate.getFileHandle(GAME_SAVE_NAME);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "NotFoundError") continue;
      throw new GameFileError("unavailable", "The game folder could not be read. Check folder access.", null, {
        cause,
      });
    }
    await validateGameDirectory(candidate);
    return candidate;
  }
  throw new GameFileError(
    "unavailable",
    `Choose SaveGames or the Gridiron install folder containing ${GAME_SAVE_NAME}.`
  );
}

export async function selectGameDirectory(startIn?: FileSystemDirectoryHandle): Promise<FileSystemDirectoryHandle> {
  const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
  if (!picker || !navigator.locks) {
    throw new GameFileError(
      "unsupported",
      "This browser cannot install game saves directly. Download the .sav file instead."
    );
  }
  try {
    const selected = await picker.call(window, {
      id: "gridiron-save-games",
      mode: "readwrite",
      ...(startIn ? { startIn } : {}),
    });
    return await resolveGameDirectory(selected);
  } catch (cause) {
    if (cause instanceof GameFileError) throw cause;
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new GameFileError("cancelled", "Folder selection was cancelled.");
    }
    throw new GameFileError("unavailable", "Choose the game folder again and allow file access.", null, { cause });
  }
}
