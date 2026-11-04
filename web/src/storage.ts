const DATABASE_NAME = "gridiron-playbook";
const DATABASE_VERSION = 1;
const STORE_NAME = "working-copies";
const SESSION_KEY = "gridiron.workspace";
const RECENT_KEY = "gridiron.recent-workspace";
const ACTIVITY_KEY = "gridiron.workspace-activity";
const ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export type WorkspaceStorageErrorCode = "unavailable" | "corrupt" | "conflict" | "closed";

export class WorkspaceStorageError extends Error {
  constructor(readonly code: WorkspaceStorageErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "WorkspaceStorageError";
  }
}

export interface WorkingCopy {
  readonly version: 1;
  readonly id: string;
  readonly revision: number;
  readonly updatedAt: number;
  readonly data: string;
}

export interface WorkspaceSession {
  readonly id: string;
  readonly data: string | null;
  readonly revision: number;
  readonly pending: number;
  save(data: string): Promise<void>;
  close(): Promise<void>;
}

function validateId(id: string): void {
  if (!ID_PATTERN.test(id)) throw new WorkspaceStorageError("corrupt", "The working-copy identity is invalid.");
}

function workingCopy(value: unknown): WorkingCopy | null {
  if (value === undefined) return null;
  if (typeof value !== "object" || value === null) {
    throw new WorkspaceStorageError("corrupt", "The saved workspace is unreadable.");
  }
  const record = value as Record<string, unknown>;
  if (
    record.version !== 1 ||
    typeof record.id !== "string" ||
    !ID_PATTERN.test(record.id) ||
    typeof record.revision !== "number" ||
    !Number.isSafeInteger(record.revision) ||
    record.revision < 1 ||
    typeof record.updatedAt !== "number" ||
    !Number.isFinite(record.updatedAt) ||
    typeof record.data !== "string"
  ) {
    throw new WorkspaceStorageError("corrupt", "The saved workspace has an unsupported or invalid format.");
  }
  return {
    version: 1,
    id: record.id,
    revision: record.revision,
    updatedAt: record.updatedAt,
    data: record.data,
  };
}

function storageFailure(error: unknown): WorkspaceStorageError {
  if (error instanceof WorkspaceStorageError) return error;
  return new WorkspaceStorageError(
    "unavailable",
    "The browser could not save the working copy. Download your playbooks before closing.",
    { cause: error }
  );
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error("The storage transaction was aborted."));
    transaction.onerror = () => reject(transaction.error);
  });
}

async function openDatabase(): Promise<IDBDatabase> {
  try {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
    };
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      let rejected = false;
      request.onsuccess = () => {
        if (rejected) request.result.close();
        else resolve(request.result);
      };
      request.onerror = () => {
        rejected = true;
        reject(request.error);
      };
      request.onblocked = () => {
        rejected = true;
        reject(new Error("Another window is blocking the working-copy database."));
      };
    });
    database.onversionchange = () => database.close();
    return database;
  } catch (error) {
    throw storageFailure(error);
  }
}

export async function readWorkingCopy(id: string): Promise<WorkingCopy | null> {
  validateId(id);
  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const finished = transactionDone(transaction);
    void finished.catch(() => undefined);
    const value: unknown = await requestValue(transaction.objectStore(STORE_NAME).get(id));
    await finished;
    const copy = workingCopy(value);
    if (copy && copy.id !== id)
      throw new WorkspaceStorageError("corrupt", "The saved workspace identity does not match.");
    return copy;
  } catch (error) {
    throw storageFailure(error);
  } finally {
    database.close();
  }
}

export async function writeWorkingCopy(id: string, expectedRevision: number, data: string): Promise<WorkingCopy> {
  validateId(id);
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
    throw new WorkspaceStorageError("corrupt", "The working-copy revision is invalid.");
  }
  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readwrite", { durability: "strict" });
    const finished = transactionDone(transaction);
    // Attach a rejection handler before awaiting requests: a failed request also aborts its transaction.
    void finished.catch(() => undefined);
    const store = transaction.objectStore(STORE_NAME);
    const previous = workingCopy(await requestValue<unknown>(store.get(id)));
    if ((previous?.revision ?? 0) !== expectedRevision) {
      transaction.abort();
      await finished.catch(() => undefined);
      throw new WorkspaceStorageError("conflict", "Another window saved a newer working copy.");
    }
    if (expectedRevision >= Number.MAX_SAFE_INTEGER) {
      transaction.abort();
      await finished.catch(() => undefined);
      throw new WorkspaceStorageError("corrupt", "The working-copy revision limit was reached.");
    }
    const copy: WorkingCopy = { version: 1, id, revision: expectedRevision + 1, updatedAt: Date.now(), data };
    await requestValue(store.put(copy));
    await finished;
    return copy;
  } catch (error) {
    throw storageFailure(error);
  } finally {
    database.close();
  }
}

async function acquireOwnership(id: string): Promise<(() => void) | null> {
  if (!navigator.locks) return null;
  return new Promise((resolve, reject) => {
    void navigator.locks
      .request(`gridiron.workspace.${id}`, { ifAvailable: true }, (lock) => {
        if (!lock) {
          resolve(null);
          return;
        }
        return new Promise<void>((release) => resolve(release));
      })
      .catch(reject);
  });
}

function storedId(storage: Storage, key: string): string | null {
  const id = storage.getItem(key);
  return id && ID_PATTERN.test(id) ? id : null;
}

class BrowserWorkspace implements WorkspaceSession {
  private currentId: string;
  private contents: string | null;
  private currentRevision: number;
  private releaseOwnership: (() => void) | null;
  private queue: Promise<void> = Promise.resolve();
  private writes = 0;
  private closing = false;
  private readonly activityToken = crypto.randomUUID();

  constructor(id: string, data: string | null, revision: number, releaseOwnership: (() => void) | null) {
    this.currentId = id;
    this.contents = data;
    this.currentRevision = revision;
    this.releaseOwnership = releaseOwnership;
    window.addEventListener("focus", this.remember);
    window.addEventListener("pointerdown", this.remember, true);
    window.addEventListener("keydown", this.remember, true);
    document.addEventListener("visibilitychange", this.rememberVisible);
    if (document.hasFocus() && document.visibilityState === "visible") this.remember();
  }

  get id(): string {
    return this.currentId;
  }
  get data(): string | null {
    return this.contents;
  }
  get revision(): number {
    return this.currentRevision;
  }
  get pending(): number {
    return this.writes;
  }

  private remember = (): void => {
    if (this.closing) return;
    try {
      localStorage.setItem(ACTIVITY_KEY, this.activityToken);
      if (!this.currentRevision) return;
      sessionStorage.setItem(SESSION_KEY, this.currentId);
      localStorage.setItem(RECENT_KEY, this.currentId);
    } catch {
      // Data remains durable in IndexedDB; save() reports identifier-storage failures to the editor.
    }
  };

  private rememberVisible = (): void => {
    if (document.visibilityState === "visible") this.remember();
  };

  private async persist(data: string): Promise<void> {
    let saved: WorkingCopy;
    try {
      saved = await writeWorkingCopy(this.currentId, this.currentRevision, data);
    } catch (error) {
      if (!(error instanceof WorkspaceStorageError) || error.code !== "conflict") throw error;
      const id = crypto.randomUUID();
      const ownership = await acquireOwnership(id);
      try {
        saved = await writeWorkingCopy(id, 0, data);
      } catch (forkError) {
        ownership?.();
        throw forkError;
      }
      this.releaseOwnership?.();
      this.releaseOwnership = ownership;
    }
    this.currentId = saved.id;
    this.currentRevision = saved.revision;
    this.contents = saved.data;
    try {
      sessionStorage.setItem(SESSION_KEY, saved.id);
      if (localStorage.getItem(ACTIVITY_KEY) === this.activityToken || !storedId(localStorage, RECENT_KEY)) {
        localStorage.setItem(RECENT_KEY, saved.id);
      }
    } catch (error) {
      throw new WorkspaceStorageError(
        "unavailable",
        "The working copy was saved, but this browser cannot remember it for reopening. Download your playbooks.",
        { cause: error }
      );
    }
  }

  save(data: string): Promise<void> {
    if (this.closing) return Promise.reject(new WorkspaceStorageError("closed", "The working copy is closed."));
    this.writes += 1;
    const operation = this.queue
      .then(() => this.persist(data))
      .finally(() => {
        this.writes -= 1;
      });
    this.queue = operation.catch(() => undefined);
    return operation;
  }

  async close(): Promise<void> {
    if (this.closing) return this.queue;
    this.closing = true;
    window.removeEventListener("focus", this.remember);
    window.removeEventListener("pointerdown", this.remember, true);
    window.removeEventListener("keydown", this.remember, true);
    document.removeEventListener("visibilitychange", this.rememberVisible);
    await this.queue;
    this.releaseOwnership?.();
    this.releaseOwnership = null;
  }
}

export async function openWorkspace(): Promise<WorkspaceSession> {
  let releaseOwnership: (() => void) | null = null;
  try {
    const sourceId = storedId(sessionStorage, SESSION_KEY) ?? storedId(localStorage, RECENT_KEY);
    const source = sourceId ? await readWorkingCopy(sourceId) : null;
    let id = source?.id ?? crypto.randomUUID();
    releaseOwnership = await acquireOwnership(id);
    let revision = source?.revision ?? 0;
    if (!releaseOwnership) {
      id = crypto.randomUUID();
      revision = 0;
      releaseOwnership = await acquireOwnership(id);
    }
    const session = new BrowserWorkspace(id, source?.data ?? null, revision, releaseOwnership);
    try {
      if (source) await session.save(source.data);
      return session;
    } catch (error) {
      await session.close();
      throw error;
    }
  } catch (error) {
    releaseOwnership?.();
    throw storageFailure(error);
  }
}
