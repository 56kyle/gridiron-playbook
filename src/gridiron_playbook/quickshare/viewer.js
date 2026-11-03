import fieldData from './field-data.js';
import {decodeShare, MAX_SHARE_BYTES} from './decode.js';

const byId = id => document.getElementById(id);
const formations = new Map(Object.entries(fieldData.formations));
const offsets = fieldData.blockOffsets;
const halfWidth = Math.abs(offsets[0][0]);
let snapshot;
let received;
let generation = 0;

function endsWithBlock(points) {
  const start = points.length - offsets.length;
  if (start <= 0) return false;
  const center = points.at(-1), anchor = points[start - 1];
  if (anchor.x !== center.x || anchor.y !== center.y || anchor.z !== center.z) return false;
  const sx = (points.at(-2).x - center.x) / halfWidth;
  const sy = (points.at(-2).y - center.y) / halfWidth;
  if (Math.abs(Math.hypot(sx, sy) - 1) * halfWidth > fieldData.blockTolerance) return false;
  return offsets.every(([side, depth], i) => {
    const p = points[start + i];
    return p.z === center.z && Math.hypot(
      (p.x - center.x) - (side * sx + depth * sy),
      (p.y - center.y) - (side * sy - depth * sx),
    ) <= fieldData.blockTolerance;
  });
}

function routeYards(points, origin) {
  const path = [];
  for (const point of points) {
    path.push(point);
    if (endsWithBlock(path)) path.length -= offsets.length;
  }
  let previous = origin, distance = 0;
  for (const p of path) {
    if (previous) distance += Math.hypot(p.x - previous.x, p.y - previous.y) / fieldData.cmPerYard;
    previous = p;
  }
  return distance % 1 === 0.5 ? 2 * Math.round(distance / 2) : Math.round(distance);
}

function projection(play, lineup) {
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  function include(x, y) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  for (const [, x, y] of Object.values(lineup)) include(x, y);
  for (const route of play.routes) for (const p of route.points) include(p.x, p.y);
  const scale = Math.min(704 / Math.max(3200, maxY - minY), 534 / Math.max(1800, maxX - minX));
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return ({x, y}) => [400 + (y - cy) * scale, 315 - (x - cx) * scale];
}

function svg(tag, attributes, text) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text !== undefined) element.textContent = text;
  return element;
}

function drawPlayer(label, position, slot, project) {
  const [x, y] = project(position);
  const group = svg('g', {'data-position': label, 'data-lineup-slot': slot, transform: 'translate(' + x + ' ' + y + ')'});
  group.append(svg('title', {}, label + ' · Slot ' + slot));
  group.append(svg('rect', {x: -15, y: -13, width: 30, height: 26, rx: 12,
    fill: 'var(--pb-input)', stroke: 'var(--pb-position-color)', 'stroke-width': 2}));
  group.append(svg('text', {'text-anchor': 'middle', dy: 5, fill: 'var(--pb-ink)', 'font-size': 14,
    'font-weight': 750}, label === 'WR-L' || label === 'WR-R' ? 'WR' : label));
  byId('lineup').append(group);
}

function drawRoute(route, index, lineup, project) {
  const player = lineup[route.slot];
  const label = player ? player[0] : 'Slot ' + route.slot;
  const origin = player ? {x: player[1], y: player[2]} : null;
  const coordinates = route.points.map(project);
  if (origin) coordinates.unshift(project(origin));
  const group = svg('g', {'data-route-index': index, 'data-position': label});
  const line = svg('polyline', {points: coordinates.map(p => p.join(',')).join(' '), fill: 'none',
    stroke: 'var(--pb-position-color)', 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'});
  if (route.points.length && !endsWithBlock(route.points)) line.setAttribute('marker-end', 'url(#arrow)');
  group.append(line);
  if (!origin && coordinates.length) {
    const [x, y] = coordinates[0];
    group.append(svg('circle', {cx: x, cy: y, r: 4, fill: 'var(--pb-position-color)'}));
    group.append(svg('text', {x: x + 8, y: y - 8, fill: 'var(--pb-position-color)'}, label));
  }
  byId('paths').append(group);

  const row = document.createElement('li');
  row.className = 'pb-preview-route';
  row.dataset.position = label;
  const dot = document.createElement('span'), name = document.createElement('strong'), yards = document.createElement('span');
  dot.className = 'pb-dot'; name.textContent = label; yards.className = 'pb-route-yardage';
  const length = routeYards(route.points, origin);
  yards.textContent = length + (length === 1 ? ' yd' : ' yds');
  yards.dataset.testid = 'preview-yardage';
  row.append(dot, name, yards);
  byId('routes').append(row);
}

function showPlay(index) {
  const play = snapshot.plays[index];
  byId('play').hidden = false;
  byId('title').textContent = play.play_name || '(Unnamed play)';
  byId('formation').textContent = play.formation_name;
  const lineup = formations.get(play.formation_name) ?? {};
  const project = projection(play, lineup);
  const baseline = project({x: 0, y: 0})[1];
  byId('baseline').setAttribute('y1', baseline);
  byId('baseline').setAttribute('y2', baseline);
  byId('grid').setAttribute('y', baseline);
  byId('paths').replaceChildren(); byId('lineup').replaceChildren(); byId('routes').replaceChildren();
  play.routes.forEach((route, i) => drawRoute(route, i, lineup, project));
  for (const [slot, [label, x, y]] of Object.entries(lineup)) drawPlayer(label, {x, y}, slot, project);
  if (!play.routes.length) byId('routes').textContent = 'No routes';
}

function status(message) {
  byId('status').textContent = message;
  byId('status').hidden = !message;
}

function filterPlays() {
  const query = byId('search').value.trim().toLowerCase();
  const select = byId('plays'), options = document.createDocumentFragment();
  snapshot.plays.forEach((play, i) => {
    const label = (i + 1) + '. ' + (play.play_name || '(Unnamed play)') + ' · ' + play.formation_name;
    if (label.toLowerCase().includes(query)) options.append(new Option(label, String(i)));
  });
  select.replaceChildren(options);
  select.disabled = !select.options.length;
  byId('play').hidden = select.disabled;
  status(select.disabled ? 'No matching plays.' : '');
  if (!select.disabled) showPlay(Number(select.value));
}

function fragmentBytes(fragment) {
  const prefix = '#v1/';
  if (!fragment.startsWith(prefix)) throw new Error('Unsupported Quickshare link.');
  const token = fragment.slice(prefix.length);
  if (token.length > Math.ceil(4 * MAX_SHARE_BYTES / 3)) throw new Error('This share exceeds the size limit.');
  if (!token || /[^A-Za-z0-9_-]/.test(token) || token.length % 4 === 1) throw new Error('Invalid Quickshare link.');
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  const rest = token.length % 4;
  if (rest && (alphabet.indexOf(token.at(-1)) & (rest === 2 ? 15 : 3))) throw new Error('Invalid Quickshare link.');
  const binary = atob(token.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function openShare(file) {
  const request = ++generation;
  snapshot = undefined; received = undefined;
  byId('snapshot').hidden = true; byId('download').hidden = true;
  if (!file && !location.hash) {
    status('Open a Quickshare link or choose a .gridironshare file.');
    return;
  }
  status('Opening share…');
  try {
    if (file && file.size > MAX_SHARE_BYTES) throw new Error('This file exceeds the size limit.');
    const bytes = file ? new Uint8Array(await file.arrayBuffer()) : fragmentBytes(location.hash);
    const decoded = await decodeShare(bytes);
    if (request !== generation) return;
    snapshot = decoded; received = bytes;
    byId('search').value = '';
    byId('library').hidden = decoded.kind === 'play';
    byId('snapshot').hidden = false; byId('download').hidden = false;
    filterPlays();
  } catch (error) {
    if (request === generation) status('Could not open this share. ' + error.message);
  }
}

byId('search').addEventListener('input', filterPlays);
byId('plays').addEventListener('change', event => showPlay(Number(event.target.value)));
byId('upload').addEventListener('change', event => {
  const file = event.target.files[0];
  if (!file) return;
  history.replaceState(null, '', location.pathname + location.search);
  event.target.value = '';
  void openShare(file);
});
byId('download').addEventListener('click', () => {
  if (!received) return;
  const url = URL.createObjectURL(new Blob([received], {type: 'application/octet-stream'}));
  const link = document.createElement('a');
  link.href = url; link.download = snapshot.kind + '.gridironshare'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener('hashchange', () => void openShare());
void openShare();
