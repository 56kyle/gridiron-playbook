import init, * as core from "./wasm/gridiron_wasm";

interface Request {
  id: number;
  method: string;
  args: unknown[];
}
let ready: Promise<unknown> | undefined;
let initialized = false;
function stringArg(args: unknown[], index: number): string {
  const value = args[index];
  if (typeof value !== "string") throw new Error("Expected text.");
  return value;
}
function bytesArg(args: unknown[], index: number): Uint8Array {
  const value = args[index];
  if (!(value instanceof Uint8Array)) throw new Error("Expected file bytes.");
  return value;
}
function indexArg(args: unknown[], index: number): number {
  const value = args[index];
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new Error("Expected a nonnegative index.");
  return value;
}
function dispatch({ method, args }: Request): unknown {
  switch (method) {
    case "new_document":
      return core.new_document();
    case "validate_document":
      return core.validate_document(stringArg(args, 0));
    case "inspect_document":
      return core.inspect_document(stringArg(args, 0));
    case "formation_data":
      return core.formation_data();
    case "decode_save":
      return core.decode_save(bytesArg(args, 0));
    case "encode_save":
      return core.encode_save(stringArg(args, 0));
    case "apply_edit":
      return core.apply_edit(stringArg(args, 0), stringArg(args, 1));
    case "transfer_plays":
      return core.transfer_plays(
        stringArg(args, 0),
        stringArg(args, 1),
        stringArg(args, 2),
        indexArg(args, 3),
        stringArg(args, 4)
      );
    case "encode_share":
      return core.encode_share(stringArg(args, 0), stringArg(args, 1), stringArg(args, 2), stringArg(args, 3));
    case "inspect_share":
      return core.inspect_share(bytesArg(args, 0));
    case "import_share":
      return core.import_share(stringArg(args, 0), bytesArg(args, 1));
    default:
      throw new Error("Unknown file operation.");
  }
}
globalThis.addEventListener("message", async (event: MessageEvent<Request>) => {
  try {
    await (ready ??= init());
    initialized = true;
    const result = dispatch(event.data);
    globalThis.postMessage({ id: event.data.id, result });
  } catch (error: unknown) {
    const fatal = !initialized || error instanceof WebAssembly.RuntimeError;
    const message = error instanceof Error ? error.message : String(error);
    let code = fatal ? "invalid_save" : "engine";
    let detail = message;
    try {
      const parsed: unknown = JSON.parse(message);
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "code" in parsed &&
        "message" in parsed &&
        typeof parsed.code === "string" &&
        typeof parsed.message === "string"
      ) {
        code = parsed.code;
        detail = parsed.message;
      }
    } catch {
      /* Native error text is already suitable for display. */
    }
    globalThis.postMessage({
      id: event.data.id,
      error: fatal ? "This file could not be processed. Your working copies are unchanged." : detail,
      code,
      fatal,
    });
  }
});
