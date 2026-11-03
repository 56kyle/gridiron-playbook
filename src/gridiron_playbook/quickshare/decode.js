// The wire format and bounds match quickshare/codec.py and snapshot.py.
export const MAX_SHARE_BYTES = 16 * 1024 * 1024;
const MAX_PLAYS = 2000;
const MAX_POINTS_PER_PLAY = 16384;
const MAX_TOTAL_POINTS = 200000;
const MAX_XY = Number.MAX_VALUE / (4 * MAX_POINTS_PER_PLAY);
const GRID_LIMIT = 2 ** 30 - 1;
const textDecoder = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true});

// Wire v2 freezes these 13 sweeps, the sideways return stroke, and the final anchor.
function v2BlockOffsets() {
  const offsets = [];
  let side = -1.5 * 91.44;
  for (let row = 0; row <= 12; row++) {
    const depth = 1.25 * 91.44 * (row / 12 - 0.5);
    offsets.push([side, depth]);
    side = -side;
    offsets.push([side, depth]);
  }
  offsets.push([side, 0]);
  return offsets;
}

const BLOCK_OFFSETS = v2BlockOffsets();
const BLOCK_POINTS = BLOCK_OFFSETS.length + 1;

function fieldPoint(x, y, z) {
  if (!(Math.abs(x) <= MAX_XY && Math.abs(y) <= MAX_XY && Number.isFinite(z))) {
    throw new Error('Route coordinates must be finite and fit the field diagram.');
  }
  return {x, y, z};
}

function appendBlock(points, center, ux, uy) {
  if (!Number.isFinite(ux) || !Number.isFinite(uy) || Math.abs(Math.hypot(ux, uy) - 1) > 1e-12) {
    throw new Error('Invalid Quickshare block direction.');
  }
  for (const [side, depth] of BLOCK_OFFSETS) {
    const x = center.x + (depth * ux - side * uy);
    const y = center.y + (depth * uy + side * ux);
    points.push(fieldPoint(x, y, center.z));
  }
  points.push(center);
}

async function inflate(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length > MAX_SHARE_BYTES) {
    throw new Error('The Quickshare size limit is 16 MiB.');
  }
  const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > MAX_SHARE_BYTES) {
        await reader.cancel();
        throw new Error('The Quickshare size limit is 16 MiB.');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const raw = new Uint8Array(length);
  let at = 0;
  for (const chunk of chunks) {
    raw.set(chunk, at);
    at += chunk.length;
  }
  return raw;
}

class Reader {
  constructor(raw) {
    this.raw = raw;
    this.view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    this.at = 0;
    this.pointsLeft = MAX_TOTAL_POINTS;
  }

  take(size) {
    const start = this.at;
    if (size > this.raw.length - start) throw new Error('The Quickshare data is incomplete.');
    this.at += size;
    return start;
  }

  byte() { return this.view.getUint8(this.take(1)); }

  uint(limit) {
    let value = 0;
    for (let factor = 1; factor <= Math.max(1, limit); factor *= 128) {
      const byte = this.byte();
      value += (byte & 127) * factor;
      if (byte < 128) {
        if (value <= limit && (factor === 1 || byte !== 0)) return value;
        break;
      }
    }
    throw new Error('Invalid Quickshare count or coordinate.');
  }

  text() {
    const size = this.uint(4096);
    const at = this.take(size);
    const value = textDecoder.decode(this.raw.subarray(at, at + size));
    if (Array.from(value).length > 1024 || value.includes('\0')) throw new Error('Invalid play or formation name.');
    return value;
  }

  blockDirection(points, anchor, mode) {
    const tag = this.byte();
    if (tag === 0 && mode === 0 && anchor > 0) {
      const dx = points[anchor].x - points[anchor - 1].x;
      const dy = points[anchor].y - points[anchor - 1].y;
      const length = Math.sqrt(dx * dx + dy * dy);
      if (length > 0 && Number.isFinite(length)) return [dx / length, dy / length];
    } else if (tag === 1 && mode === 0) {
      return [this.view.getFloat64(this.take(8), true), this.view.getFloat64(this.take(8), true)];
    } else if (tag === 2 && mode !== 0) {
      const angle = this.view.getUint16(this.take(2), true) * (2 * Math.PI / 65536);
      return [Math.cos(angle), Math.sin(angle)];
    }
    throw new Error('Invalid Quickshare block instruction.');
  }

  expandBlocks(points, mode, remaining) {
    const count = this.uint(Math.floor(Math.min(remaining, this.pointsLeft) / BLOCK_POINTS));
    if (!count || !points.length) throw new Error('Empty Quickshare block table or route.');
    this.pointsLeft -= count * BLOCK_POINTS;
    const expanded = [];
    let next = 0;
    for (let i = 0; i < count; i++) {
      const anchor = this.uint(points.length - 1);
      if (anchor < next - 1) throw new Error('Quickshare block anchors must be in route order.');
      while (next <= anchor) expanded.push(points[next++]);
      const [ux, uy] = this.blockDirection(points, anchor, mode);
      appendBlock(expanded, points[anchor], ux, uy);
    }
    while (next < points.length) expanded.push(points[next++]);
    return expanded;
  }

  route(remaining, version) {
    const slot = this.byte();
    const flags = this.byte();
    const hasBlocks = version === 2 && (flags & 8) !== 0;
    const coordinateFlags = hasBlocks ? flags - 8 : flags;
    if (coordinateFlags > 5) throw new Error('Unknown Quickshare coordinate format.');
    const mode = coordinateFlags >> 1;
    const axes = flags & 1 ? 3 : 2;
    const count = this.uint(Math.min(remaining, this.pointsLeft));
    this.pointsLeft -= count;
    const previous = [0, 0, 0];
    const points = [];
    for (let index = 0; index < count; index++) {
      const coords = [0, 0, 0];
      for (let axis = 0; axis < axes; axis++) {
        if (mode === 0) {
          coords[axis] = this.view.getFloat64(this.take(8), true);
        } else {
          const code = this.uint(4 * GRID_LIMIT);
          previous[axis] += code % 2 ? -(code + 1) / 2 : code / 2;
          if (Math.abs(previous[axis]) > GRID_LIMIT) throw new Error('Quickshare grid coordinate is out of range.');
          coords[axis] = previous[axis] / (mode === 1 ? 10 : 1);
        }
      }
      points.push(fieldPoint(...coords));
    }
    return {slot, points: hasBlocks ? this.expandBlocks(points, mode, remaining - count) : points};
  }

  play(formations, version) {
    const formation_name = formations[this.uint(formations.length - 1)];
    const play_name = this.text();
    const routeCount = this.uint(256);
    const routes = [];
    let remaining = MAX_POINTS_PER_PLAY;
    for (let index = 0; index < routeCount; index++) {
      const route = this.route(remaining, version);
      remaining -= route.points.length;
      routes.push(route);
    }
    return {formation_name, play_name, routes};
  }
}

export async function decodeShare(bytes) {
  const reader = new Reader(await inflate(bytes));
  const header = reader.view.getUint32(reader.take(4));
  if (header !== 0x47515301 && header !== 0x47515302) throw new Error('Unknown Quickshare file format or version.');
  const version = header & 255;
  const kind = reader.byte();
  if (kind > 1) throw new Error('Unknown Quickshare selection.');
  const formationCount = reader.uint(MAX_PLAYS);
  if (!formationCount) throw new Error('The Quickshare formation table is empty.');
  const formations = Array.from({length: formationCount}, () => reader.text());
  const count = reader.uint(kind === 0 ? 1 : MAX_PLAYS);
  if (!count) throw new Error('The Quickshare selection is empty.');
  const plays = Array.from({length: count}, () => reader.play(formations, version));
  if (reader.at !== reader.raw.length) throw new Error('Unexpected trailing Quickshare data.');
  return {version: 1, kind: kind === 0 ? 'play' : 'playbook', plays};
}
