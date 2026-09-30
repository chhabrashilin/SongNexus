import { forwardRef, useEffect, useId, useState } from "react";

import { api } from "../services/api";
import type { EntityType, SearchResult } from "../types/api";
import { SearchIcon } from "./Icons";

interface Props {
  placeholder: string;
  onPick: (result: SearchResult) => void;
  types?: EntityType[];
  label: string;
  autoFocus?: boolean;
  compact?: boolean;
  shortcut?: string;
}

const DEBOUNCE_MS = 140;

/** Accessible autocomplete (ARIA combobox): arrows to move, Enter to pick, Escape to close. */
export const SearchBox = forwardRef<HTMLInputElement, Props>(function SearchBox(
  { placeholder, onPick, types, label, autoFocus, compact, shortcut },
  ref,
) {
  const [query, setQuery] = useState("");
  // Results remember the query they answer, so a stale list is never shown or picked.
  const [answered, setAnswered] = useState<{ query: string; results: SearchResult[] }>({ query: "", results: [] });
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listId = useId();
  // A string key keeps the effect stable when callers pass a new array each render.
  const typesKey = types?.join(",") ?? "";

  useEffect(() => {
    const q = query.trim();
    if (!q) return; // the list is hidden for an empty query; stale results are never shown
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const entityTypes = typesKey ? (typesKey.split(",") as EntityType[]) : undefined;
      api.search(q, controller.signal, entityTypes).then(
        (response) => {
          setAnswered({ query: q, results: response.results });
          setActive(0);
          setOpen(true);
          setError(null);
        },
        (err: unknown) => {
          if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Search failed");
        },
      );
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, typesKey]);

  const current = query.trim();
  const fresh = answered.query === current;
  const results = fresh ? answered.results : [];

  const pick = (result: SearchResult | undefined) => {
    if (!result) return;
    onPick(result);
    setQuery("");
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
      setOpen(true);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(results[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
      (event.target as HTMLInputElement).blur();
    }
  };

  const showList = open && current.length > 0;
  return (
    <div className={`search-box${compact ? " compact" : ""}`}>
      <div className="search-field">
        <span className="search-icon">
          <SearchIcon size={compact ? 15 : 17} />
        </span>
        <input
          ref={ref}
          type="search"
          role="combobox"
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
          placeholder={placeholder}
          value={query}
          autoFocus={autoFocus}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        />
        {shortcut && !query && <kbd aria-hidden="true">{shortcut}</kbd>}
      </div>
      {showList && (
        <ul className="search-results" id={listId} role="listbox">
          {error && <li className="search-empty">{error}</li>}
          {!error && !fresh && <li className="search-empty">Searching…</li>}
          {!error && fresh && results.length === 0 && <li className="search-empty">No matches in the dataset</li>}
          {results.map((r, i) => (
            <li
              key={`${r.entity_type}:${r.id}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(r)}
              onMouseEnter={() => setActive(i)}
            >
              <span className="badge">{r.entity_type}</span>
              <span className="result-text">
                <span className="result-name">{r.name}</span>
                <span className="result-subtitle">
                  {r.matched_on !== r.name ? `matched “${r.matched_on}” · ` : ""}
                  {r.subtitle}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});
