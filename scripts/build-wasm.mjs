import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const executable = process.platform === "win32" ? "wasm-bindgen.exe" : "wasm-bindgen";
const local = path.join(root, ".tools", "bin", executable);
const bindgen = existsSync(local) ? local : "wasm-bindgen";
function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  if (result.error) {
    console.error(`${command}: ${result.error.message}`);
    console.error("Setup: rustup target add wasm32-unknown-unknown");
    console.error("       cargo install wasm-bindgen-cli --version 0.2.130 --locked --root .tools");
  }
  if (result.error || result.status !== 0) process.exit(result.status || 1);
}
run("cargo", [
  "build",
  "--manifest-path",
  "rust/Cargo.toml",
  "-p",
  "gridiron-wasm",
  "--locked",
  "--release",
  "--target",
  "wasm32-unknown-unknown",
]);
mkdirSync(path.join(root, "web", "src", "wasm"), { recursive: true });
run(bindgen, [
  "rust/target/wasm32-unknown-unknown/release/gridiron_wasm.wasm",
  "--target",
  "web",
  "--out-dir",
  "web/src/wasm",
  "--out-name",
  "gridiron_wasm",
]);
