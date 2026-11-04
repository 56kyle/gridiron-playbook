import type {
  DocumentView,
  EditCommand,
  Formation,
  ImportedShare,
  ShareKind,
  SharePrecision,
  ShareView,
  TransferredPlays,
} from "./types";

export class EngineError extends Error {
  constructor(message: string, readonly code = "engine") {
    super(message);
    this.name = "EngineError";
  }
}

interface Reply {
  id: number;
  result?: unknown;
  error?: string;
  code?: string;
  fatal?: boolean;
}
interface Pending {
  resolve: (result: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}
let worker: Worker | null = null;
let sequence = 0;
const pending = new Map<number, Pending>();
const TIMEOUT_MS = 60_000;

function discard(error: Error): void {
  worker?.terminate();
  worker = null;
  for (const request of pending.values()) {
    clearTimeout(request.timer);
    request.reject(error);
  }
  pending.clear();
}
function getWorker(): Worker {
  if (worker) return worker;
  const next = new Worker(new URL("./engine.worker.ts", import.meta.url), { type: "module" });
  next.onmessage = (event: MessageEvent<Reply>) => {
    if (worker !== next) return;
    const response = event.data;
    if (response.fatal) {
      discard(new EngineError(response.error ?? "The save could not be read.", response.code ?? "engine"));
      return;
    }
    const request = pending.get(response.id);
    if (!request) return;
    clearTimeout(request.timer);
    pending.delete(response.id);
    if (response.error !== undefined) request.reject(new EngineError(response.error, response.code));
    else request.resolve(response.result);
  };
  next.onerror = (event) => {
    if (worker !== next) return;
    event.preventDefault();
    discard(new EngineError("The file processor stopped. Your working copies are unchanged; try again."));
  };
  next.onmessageerror = () => {
    if (worker === next) discard(new EngineError("The file processor returned an invalid response."));
  };
  worker = next;
  return next;
}
function call(method: string, ...args: unknown[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const active = getWorker();
    const id = ++sequence;
    const timer = setTimeout(
      () =>
        discard(new EngineError("The file took too long to process. Your working copies are unchanged.", "timeout")),
      TIMEOUT_MS
    );
    pending.set(id, { resolve, reject, timer });
    try {
      active.postMessage({ id, method, args });
    } catch (error) {
      clearTimeout(timer);
      pending.delete(id);
      reject(error);
    }
  });
}
async function text(method: string, ...args: unknown[]): Promise<string> {
  const result = await call(method, ...args);
  if (typeof result !== "string") throw new EngineError("The file processor returned an invalid document.");
  return result;
}
async function bytes(method: string, ...args: unknown[]): Promise<Uint8Array> {
  const result = await call(method, ...args);
  if (!(result instanceof Uint8Array)) throw new EngineError("The file processor returned invalid bytes.");
  return result;
}
// These views are produced by the validated Rust core; complete documents never pass through JSON.parse.
async function view<T>(method: string, ...args: unknown[]): Promise<T> {
  return JSON.parse(await text(method, ...args)) as T;
}
export const newDocument = (): Promise<string> => text("new_document");
export const decodeSave = (data: Uint8Array): Promise<string> => text("decode_save", data);
export const encodeSave = (document: string): Promise<Uint8Array> => bytes("encode_save", document);
export const validateDocument = async (document: string): Promise<void> => {
  await call("validate_document", document);
};
export const inspectDocument = (document: string): Promise<DocumentView> => view("inspect_document", document);
export const formationData = (): Promise<Formation[]> => view("formation_data");
export const applyEdit = (document: string, command: EditCommand): Promise<string> =>
  text("apply_edit", document, JSON.stringify(command));
export const transferPlays = (
  source: string,
  target: string,
  indices: number[],
  insertion: number,
  mode: "copy" | "move"
): Promise<TransferredPlays> => view("transfer_plays", source, target, JSON.stringify(indices), insertion, mode);
export const encodeShare = (
  document: string,
  indices: number[],
  kind: ShareKind,
  precision: SharePrecision
): Promise<Uint8Array> => bytes("encode_share", document, JSON.stringify(indices), kind, precision);
export const inspectShare = (data: Uint8Array): Promise<ShareView> => view("inspect_share", data);
export const importShare = (template: string, data: Uint8Array): Promise<ImportedShare> =>
  view("import_share", template, data);
