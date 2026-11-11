// Plan geometry shared by the layout editor and the live view.
// Layout is stored in grid cells; the SVG draws CELL px per cell.
export const CELL = 25;
export const NS = 'http://www.w3.org/2000/svg';

export function mk(tag, attrs, parent, text) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}

export const px = (r) => ({ x: r.x * CELL, y: r.y * CELL, w: r.w * CELL, h: r.h * CELL });

// Point where the segment from rect centre towards (tx, ty) leaves the rect.
function exitPoint(r, tx, ty) {
  const cx = r.x + r.w / 2, cy = r.y + r.h / 2, dx = tx - cx, dy = ty - cy;
  if (!dx && !dy) return { x: cx, y: cy };
  const s = Math.min(dx ? (r.w / 2) / Math.abs(dx) : Infinity, dy ? (r.h / 2) / Math.abs(dy) : Infinity);
  return { x: cx + dx * s, y: cy + dy * s };
}

// SVG path "d" for a path between two zones (edge to edge, through centres).
export function pathD(a, b) {
  const A = px(a), B = px(b);
  const p = exitPoint(A, B.x + B.w / 2, B.y + B.h / 2);
  const q = exitPoint(B, A.x + A.w / 2, A.y + A.h / 2);
  return `M${p.x} ${p.y} L${q.x} ${q.y}`;
}

// Door marker on the outline edge nearest an entry zone.
export function doorFor(z, o) {
  const Z = px(z), O = px(o);
  const d = [
    ['top', Math.abs(Z.y - O.y)], ['bottom', Math.abs(Z.y + Z.h - (O.y + O.h))],
    ['left', Math.abs(Z.x - O.x)], ['right', Math.abs(Z.x + Z.w - (O.x + O.w))],
  ].sort((m, n) => m[1] - n[1])[0][0];
  const len = Math.min(70, (d === 'top' || d === 'bottom' ? Z.w : Z.h) * 0.6), t = 10;
  if (d === 'top' || d === 'bottom') {
    const x = Z.x + Z.w / 2 - len / 2, y = (d === 'top' ? O.y : O.y + O.h) - t / 2;
    return { x, y, width: len, height: t, lx: x + len / 2, ly: d === 'top' ? y - 6 : y + t + 16 };
  }
  const y = Z.y + Z.h / 2 - len / 2, x = (d === 'left' ? O.x : O.x + O.w) - t / 2;
  return { x, y, width: t, height: len, lx: d === 'left' ? x - 22 : x + t + 22, ly: y + len / 2 + 5 };
}

export function drawDoor(z, outline, parent) {
  if (!outline) return;
  const d = doorFor(z, outline);
  mk('rect', { x: d.x, y: d.y, width: d.width, height: d.height, class: 'door' }, parent);
  mk('text', { x: d.lx, y: d.ly, 'text-anchor': 'middle', class: 'door-t' }, parent, 'Door');
}

export const roleOf = (roles, key) => roles.find((r) => r.key === key) || { key, label: key, behaviour: {} };
export const isOutside = (role) => role.behaviour?.outline === 'outside';
export const isDoor = (role) => role.behaviour?.outline === 'door';
