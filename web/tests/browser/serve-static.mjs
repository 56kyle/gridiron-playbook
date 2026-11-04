import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";

const root = resolve("dist");
const prefix = "/gridiron-playbook/";
const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".wasm": "application/wasm",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
    if (pathname === prefix.slice(0, -1)) {
      response.writeHead(308, { Location: prefix });
      response.end();
      return;
    }
    if (!pathname.startsWith(prefix)) throw new Error("Not found");
    let filename = resolve(root, pathname.slice(prefix.length));
    if (filename !== root && !filename.startsWith(root + sep)) throw new Error("Not found");
    if ((await stat(filename)).isDirectory()) filename = resolve(filename, "index.html");
    const bytes = await readFile(filename);
    response.writeHead(200, {
      "Content-Type": contentTypes[extname(filename)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(bytes);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
}).listen(4173, "127.0.0.1");
