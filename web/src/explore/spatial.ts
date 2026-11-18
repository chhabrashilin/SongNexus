/**
 * Geometry for moving through the connection web with the keyboard. Pure, so
 * it is unit-tested apart from the canvas.
 */

export interface Point {
  id: string;
  x: number;
  y: number;
}

/** Arrow keys as screen directions (the canvas is spatial, not textual). */
export const ARROWS: Record<string, readonly [number, number]> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  ArrowDown: [0, 1],
  ArrowUp: [0, -1],
};

/**
 * The artist the eye would go to next in a direction: ahead of `from` (within a
 * 60° cone either side), preferring what is straight ahead over what is close
 * but off to the side. Null when nothing lies that way.
 */
export function nearestInDirection(
  points: Iterable<Point>,
  from: Point,
  dx: number,
  dy: number,
): string | null {
  let best: string | null = null;
  let bestScore = Infinity;
  for (const point of points) {
    if (point.id === from.id) continue;
    const vx = point.x - from.x;
    const vy = point.y - from.y;
    const along = vx * dx + vy * dy;
    if (along <= 0) continue;
    const across = Math.abs(vx * dy - vy * dx);
    // tan(60°) ≈ 1.73: anything further off-axis belongs to another arrow.
    if (across > along * 1.73) continue;
    const score = along + 2 * across;
    if (score < bestScore) {
      bestScore = score;
      best = point.id;
    }
  }
  return best;
}

/** Ease in and out (cubic), for the camera. */
export function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

export interface View {
  x: number;
  y: number;
  k: number;
}

/**
 * A camera position between two views. Zoom moves geometrically (so zooming
 * from 0.5 to 2 feels as even as 1 to 4) and the point at the middle of the
 * screen travels in a straight line, so the web glides instead of swinging.
 */
export function interpolateView(from: View, to: View, t: number): View {
  const k = from.k * Math.pow(to.k / from.k, t);
  const cx = -from.x / from.k + (-to.x / to.k - -from.x / from.k) * t;
  const cy = -from.y / from.k + (-to.y / to.k - -from.y / from.k) * t;
  return {x: -cx * k, y: -cy * k, k};
}
