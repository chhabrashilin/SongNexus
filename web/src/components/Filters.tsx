/** Connection-category toggles (doubling as the legend) and the genre filter (US-12). */
import {useId, useMemo, useState} from 'react';

import {useGenres} from '../api/queries';
import {useI18n} from '../i18n/i18n';

import {CATEGORIES, CATEGORY_ENCODING, type Category} from './encoding';
import {Icon} from './Icon';

export function Swatch({category}: {category: Category}) {
  const {color, dash} = CATEGORY_ENCODING[category];
  return (
    <svg
      className="swatch"
      viewBox="0 0 18 4"
      aria-hidden="true"
      style={{blockSize: 4}}
    >
      <line
        x1="0"
        y1="2"
        x2="18"
        y2="2"
        stroke={color}
        strokeWidth="3"
        strokeDasharray={dash.join(' ')}
      />
    </svg>
  );
}

export function CategoryChips({
  value,
  onChange,
}: {
  value: readonly Category[];
  onChange: (next: Category[]) => void;
}) {
  const {t} = useI18n();
  const labelId = useId();
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className="stack"
      style={{gap: 'var(--space-2)'}}
    >
      <span id={labelId} className="muted" style={{font: 'var(--label-large)'}}>
        {t('filter.categories')}
      </span>
      <div className="chips">
        {CATEGORIES.map(category => {
          const on = value.includes(category);
          return (
            <button
              key={category}
              type="button"
              className="chip"
              aria-pressed={on}
              onClick={() => {
                const next = on
                  ? value.filter(c => c !== category)
                  : [...value, category];
                // At least one category stays on; an empty set would show nothing.
                if (next.length > 0) onChange(next);
              }}
            >
              {on && <Icon name="check" size={18} />}
              <Swatch category={category} />
              {t(`category.${category}`)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface GenreFilterProps {
  value: readonly string[];
  onChange: (next: string[]) => void;
  includeUnknown: boolean;
  onIncludeUnknownChange: (next: boolean) => void;
  /** Share of artists in view with genre data, shown honestly (AC-12.2). */
  coverage?: number | undefined;
}

export function GenreFilter({
  value,
  onChange,
  includeUnknown,
  onIncludeUnknownChange,
  coverage,
}: GenreFilterProps) {
  const {t} = useI18n();
  const genres = useGenres();
  const [query, setQuery] = useState('');
  const labelId = useId();
  const all = genres.data ?? [];
  const names = useMemo(
    () => new Map(all.map(g => [g.name, g.displayName])),
    [all],
  );
  const matches = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return all
      .filter(
        g =>
          !value.includes(g.name) &&
          (!q || g.displayName.toLocaleLowerCase().includes(q)),
      )
      .slice(0, 12);
  }, [all, query, value]);

  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className="stack"
      style={{gap: 'var(--space-2)'}}
    >
      <span id={labelId} className="muted" style={{font: 'var(--label-large)'}}>
        {t('filter.genres')}
        {' · '}
        {value.length
          ? t('filter.genres.selected', {count: value.length})
          : t('filter.genres.none')}
      </span>
      {value.length > 0 && (
        <div className="chips">
          {value.map(name => (
            <button
              key={name}
              type="button"
              className="chip"
              aria-pressed="true"
              onClick={() => onChange(value.filter(v => v !== name))}
            >
              {names.get(name) ?? name}
              <Icon name="close" size={18} />
            </button>
          ))}
        </div>
      )}
      <label className="field" style={{minBlockSize: 40}}>
        <Icon name="search" size={20} />
        <span className="visually-hidden">{t('filter.genres.search')}</span>
        <input
          type="search"
          value={query}
          placeholder={t('filter.genres.search')}
          onChange={event => setQuery(event.target.value)}
        />
      </label>
      <div className="chips">
        {matches.map(genre => (
          <button
            key={genre.name}
            type="button"
            className="chip"
            aria-pressed="false"
            onClick={() => {
              onChange([...value, genre.name]);
              setQuery('');
            }}
          >
            {genre.displayName}
          </button>
        ))}
      </div>
      <label className="row" style={{minBlockSize: 'var(--touch-target)'}}>
        <input
          type="checkbox"
          checked={includeUnknown}
          onChange={event => onIncludeUnknownChange(event.target.checked)}
        />
        {t('filter.genres.includeUnknown')}
      </label>
      {coverage !== undefined && (
        <span className="muted" style={{font: 'var(--body-small)'}}>
          {t('filter.genres.coverage', {percent: coverage})}
        </span>
      )}
    </div>
  );
}
