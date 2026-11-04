export const MAX_OPEN_BYTES = 64 * 1024 * 1024;

export function downloadBytes(data: Uint8Array, filename: string, type = "application/octet-stream"): void {
  const blob = new Blob([new Uint8Array(data)], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function shareBytes(link: string): Uint8Array {
  const fragment = link.startsWith("#") ? link.slice(1) : new URL(link).hash.slice(1);
  if (!fragment.startsWith("v1/")) throw new Error("This is not a supported Quickshare link.");
  const token = fragment.slice(3);
  if (
    !token ||
    token.length > Math.ceil((16 * 1024 * 1024 * 4) / 3) ||
    !/^[A-Za-z0-9_-]+$/.test(token) ||
    token.length % 4 === 1
  )
    throw new Error("The Quickshare link is invalid or too large.");
  const binary = atob(token.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (token.length % 4)) % 4));
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (base64Url(bytes) !== token) throw new Error("The Quickshare link has invalid padding.");
  return bytes;
}

export function shareUrl(bytes: Uint8Array): string {
  return shareUrlAt(bytes, window.location.href, import.meta.env.BASE_URL);
}

export function shareUrlAt(bytes: Uint8Array, pageUrl: string, base: string): string {
  const url = new URL(base, pageUrl);
  url.search = "";
  url.hash = `v1/${base64Url(bytes)}`;
  return url.href;
}

export function fileStem(name: string): string {
  return (
    name
      .replace(/\.(sav|json|gridironshare)$/i, "")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")
      .trim() || "playbook"
  );
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
