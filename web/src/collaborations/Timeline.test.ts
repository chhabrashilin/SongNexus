import {describe, expect, it} from 'vitest';

import {columns, inRange, pick} from './Timeline';

describe('collaborations timeline', () => {
  it('fills missing years with zero so the time axis stays honest', () => {
    const data = columns([
      {year: 2001, counts: {FEATURE: 2}},
      {year: 2004, counts: {FEATURE: 1, PRODUCTION: 3}},
    ]);
    expect(data.map(c => [c.year, c.total])).toEqual([
      [2001, 2],
      [2002, 0],
      [2003, 0],
      [2004, 4],
    ]);
  });

  it('picks one year on a tap and stretches the range on a shift-tap', () => {
    const one = pick({from: null, to: null}, 2003, true);
    expect(one).toEqual({from: 2003, to: 2003});
    expect(pick(one, 2001, true)).toEqual({from: 2001, to: 2003});
    expect(pick({from: 2001, to: 2003}, 2010, false)).toEqual({
      from: 2010,
      to: 2010,
    });
  });

  it('treats open ends as unbounded', () => {
    expect(inRange(1990, {from: null, to: 2000})).toBe(true);
    expect(inRange(2001, {from: null, to: 2000})).toBe(false);
    expect(inRange(2001, {from: 2001, to: null})).toBe(true);
  });
});
