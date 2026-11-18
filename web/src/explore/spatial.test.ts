import {describe, expect, it} from 'vitest';

import {easeInOut, interpolateView, nearestInDirection} from './spatial';

const points = [
  {id: 'c', x: 0, y: 0},
  {id: 'right', x: 100, y: 10},
  {id: 'farRight', x: 300, y: 0},
  {id: 'up', x: 5, y: -80},
  {id: 'diag', x: 60, y: 70},
];

describe('nearestInDirection', () => {
  it('goes to what is straight ahead', () => {
    expect(nearestInDirection(points, points[0]!, 1, 0)).toBe('right');
    expect(nearestInDirection(points, points[0]!, 0, -1)).toBe('up');
  });

  it('returns null when nothing lies that way', () => {
    expect(nearestInDirection(points, points[0]!, -1, 0)).toBeNull();
  });

  it('ignores points far off the axis', () => {
    const only = [points[0]!, {id: 'side', x: 10, y: 200}];
    expect(nearestInDirection(only, only[0]!, 1, 0)).toBeNull();
  });

  it('prefers straight ahead over close but sideways', () => {
    expect(nearestInDirection(points, points[0]!, 0, 1)).toBe('diag');
  });
});

describe('camera', () => {
  it('eases from 0 to 1', () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(0.5)).toBeCloseTo(0.5);
  });

  it('starts and ends on the given views and zooms geometrically', () => {
    const a = {x: 10, y: -20, k: 0.5};
    const b = {x: -200, y: 40, k: 2};
    expect(interpolateView(a, b, 0)).toEqual(a);
    const end = interpolateView(a, b, 1);
    expect(end.x).toBeCloseTo(b.x);
    expect(end.y).toBeCloseTo(b.y);
    expect(end.k).toBeCloseTo(b.k);
    expect(interpolateView(a, b, 0.5).k).toBeCloseTo(1);
  });
});
