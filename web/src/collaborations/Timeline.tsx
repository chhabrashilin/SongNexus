/**
 * Collaborations per year (R2-3): one column per year, oldest left, gaps as zero
 * so the time axis stays honest. One series, so one color and no legend; the
 * selected range is also conveyed by aria-pressed and the From/To controls.
 *
 * Columns are buttons with one tab stop (arrow keys move between years). Hover
 * and focus fill the readout above the chart; the table view carries the same
 * numbers without either.
 */
import {useId, useMemo, useRef, useState, type KeyboardEvent} from 'react';

import type {Schemas} from '../api/client';
import type {CollaborationType} from '../api/queries';
import {useI18n} from '../i18n/i18n';

export interface YearRange {
  from: number | null;
  to: number | null;
}

interface Column {
  year: number;
  total: number;
  counts: Partial<Record<CollaborationType, number>>;
}

const TYPES: CollaborationType[] = ['FEATURE', 'PRODUCTION', 'BAND', 'CREDIT'];

/** Fills missing years with zero, so equal widths mean equal time. */
export function columns(timeline: Schemas['TimelineYear'][]): Column[] {
  if (timeline.length === 0) return [];
  const byYear = new Map(timeline.map(t => [t.year, t.counts]));
  const first = timeline[0]!.year;
  const last = timeline.at(-1)!.year;
  const out: Column[] = [];
  for (let year = first; year <= last; year++) {
    const counts = byYear.get(year) ?? {};
    const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
    out.push({year, total, counts});
  }
  return out;
}

export function inRange(year: number, range: YearRange): boolean {
  return (
    (range.from === null || year >= range.from) &&
    (range.to === null || year <= range.to)
  );
}

/** A tap picks one year; a shift-tap stretches the range to include it. */
export function pick(
  range: YearRange,
  year: number,
  extend: boolean,
): YearRange {
  if (!extend || range.from === null || range.to === null) {
    return {from: year, to: year};
  }
  return {from: Math.min(range.from, year), to: Math.max(range.to, year)};
}

export function Timeline({
  timeline,
  undated,
  range,
  onChange,
}: {
  timeline: Schemas['TimelineYear'][];
  undated: Partial<Record<CollaborationType, number>>;
  range: YearRange;
  onChange: (next: YearRange) => void;
}) {
  const {t} = useI18n();
  const data = useMemo(() => columns(timeline), [timeline]);
  const [active, setActive] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [asTable, setAsTable] = useState(false);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const titleId = useId();
  const undatedTotal = Object.values(undated).reduce((a, b) => a + (b ?? 0), 0);
  const max = Math.max(1, ...data.map(c => c.total));
  const filtered = range.from !== null || range.to !== null;

  const describe = (column: Column) =>
    [
      t('collab.timeline.yearTotal', {year: column.year, count: column.total}),
      ...TYPES.filter(type => column.counts[type]).map(
        type => `${t(`collab.tab.${type}`)} ${column.counts[type]}`,
      ),
    ].join(' · ');

  function onKey(event: KeyboardEvent, index: number) {
    const step =
      event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const rtl = document.documentElement.dir === 'rtl';
    const next = Math.min(
      data.length - 1,
      Math.max(0, index + (rtl ? -step : step)),
    );
    setFocusIndex(next);
    refs.current[next]?.focus();
  }

  if (data.length < 2) {
    // One year is a sentence, not a chart.
    return (
      <p className="muted">
        {data.length === 1
          ? t('collab.timeline.single', {
              year: data[0]!.year,
              count: data[0]!.total,
            })
          : t('collab.timeline.none')}
        {undatedTotal > 0 &&
          ` ${t('collab.timeline.undated', {count: undatedTotal})}`}
      </p>
    );
  }

  const readout = active !== null ? data.find(c => c.year === active) : null;
  return (
    <figure className="timeline" aria-labelledby={titleId}>
      <figcaption id={titleId} className="timeline__caption">
        <span>{t('collab.timeline.title')}</span>
        <button
          type="button"
          className="btn btn--text"
          aria-pressed={asTable}
          onClick={() => setAsTable(v => !v)}
        >
          {asTable
            ? t('collab.timeline.asChart')
            : t('collab.timeline.asTable')}
        </button>
      </figcaption>
      <p className="timeline__readout muted" aria-live="polite">
        {readout ? describe(readout) : t('collab.timeline.hint')}
      </p>
      {asTable ? (
        <table className="timeline__table">
          <thead>
            <tr>
              <th scope="col">{t('collab.timeline.year')}</th>
              <th scope="col">{t('collab.timeline.total')}</th>
              {TYPES.map(type => (
                <th key={type} scope="col">
                  {t(`collab.tab.${type}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data
              .filter(c => c.total > 0)
              .map(c => (
                <tr key={c.year}>
                  <th scope="row">{c.year}</th>
                  <td>{c.total}</td>
                  {TYPES.map(type => (
                    <td key={type}>{c.counts[type] ?? 0}</td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      ) : (
        <div className="timeline__plot">
          <span className="timeline__max muted" aria-hidden="true">
            {max}
          </span>
          <div
            className="timeline__bars"
            role="group"
            aria-label={t('collab.timeline.title')}
          >
            {data.map((column, index) => (
              <button
                key={column.year}
                ref={element => {
                  refs.current[index] = element;
                }}
                type="button"
                className="timeline__column"
                tabIndex={index === focusIndex ? 0 : -1}
                aria-label={describe(column)}
                aria-pressed={filtered && inRange(column.year, range)}
                data-in-range={!filtered || inRange(column.year, range)}
                onPointerEnter={() => setActive(column.year)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => {
                  setActive(column.year);
                  setFocusIndex(index);
                }}
                onBlur={() => setActive(null)}
                onKeyDown={event => onKey(event, index)}
                onClick={event =>
                  onChange(pick(range, column.year, event.shiftKey))
                }
              >
                <span
                  className="timeline__bar"
                  style={{blockSize: `${(column.total / max) * 100}%`}}
                />
              </button>
            ))}
          </div>
          <div className="timeline__axis muted" aria-hidden="true">
            <span>{data[0]!.year}</span>
            <span>{data.at(-1)!.year}</span>
          </div>
        </div>
      )}
      {undatedTotal > 0 && (
        <p className="muted" style={{font: 'var(--body-small)'}}>
          {t('collab.timeline.undated', {count: undatedTotal})}
        </p>
      )}
    </figure>
  );
}
