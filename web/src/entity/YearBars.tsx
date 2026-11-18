/**
 * A small column chart of counts per year (a label's releases). One series, so
 * one color and no legend; empty years stay as gaps so time reads honestly.
 * The sentence above the chart carries the same reading for screen readers;
 * the columns themselves are decoration.
 */
import {useId, type CSSProperties} from 'react';

import {useI18n} from '../i18n/i18n';

import {perYear} from './facts';

export function YearBars({
  years,
  title,
}: {
  years: (number | null)[];
  title: string;
}) {
  const {t} = useI18n();
  const captionId = useId();
  const data = perYear(years);
  if (data.length < 2) return null;
  const max = Math.max(...data.map(d => d.count));
  const peak = data.find(d => d.count === max)!;
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <figure className="yearbars" aria-labelledby={captionId}>
      <figcaption id={captionId} className="yearbars__caption">
        <span className="yearbars__title">{title}</span>
        <span className="yearbars__summary">
          {t('entity.perYear.summary', {
            count: total,
            first: data[0]!.year,
            last: data.at(-1)!.year,
            peak: peak.year,
          })}
        </span>
      </figcaption>
      <div className="yearbars__plot" aria-hidden="true">
        {data.map(d => (
          <span
            key={d.year}
            className="yearbars__col"
            title={`${d.year}: ${d.count}`}
            data-peak={d.year === peak.year || undefined}
          >
            <span
              className="yearbars__bar"
              style={{'--v': d.count / max} as CSSProperties}
            />
          </span>
        ))}
      </div>
      <div className="yearbars__axis" aria-hidden="true">
        <span>{data[0]!.year}</span>
        <span>{data.at(-1)!.year}</span>
      </div>
    </figure>
  );
}
