import { ALL_CATEGORIES, type Category } from "../types/api";
import { CATEGORY_ENCODING, CATEGORY_LABELS } from "../utils/format";
import { Swatch } from "./Swatch";

interface Props {
  categories: Category[];
  onChange: (categories: Category[]) => void;
  limit: number;
  onLimitChange: (limit: number) => void;
}

export function FilterBar({ categories, onChange, limit, onLimitChange }: Props) {
  const toggle = (category: Category) => {
    const next = categories.includes(category) ? categories.filter((c) => c !== category) : [...categories, category];
    if (next.length > 0) onChange(next);
  };
  return (
    <>
      <section className="section" aria-label="Connection types">
        <h3>Connection types</h3>
        <div className="chips">
          {ALL_CATEGORIES.map((category) => (
            <button
              key={category}
              type="button"
              className="chip toggle"
              aria-pressed={categories.includes(category)}
              onClick={() => toggle(category)}
            >
              <Swatch encoding={CATEGORY_ENCODING[category]} />
              {CATEGORY_LABELS[category]}
            </button>
          ))}
        </div>
        {categories.includes("engineering") && (
          <p className="note">
            Engineering credits link many artists through a few mix engineers, so paths become less meaningful.
          </p>
        )}
      </section>
      <section className="section">
        <label className="slider">
          <span className="slider-head">
            <span>Neighbors per artist</span>
            <strong className="num">{limit}</strong>
          </span>
          <input type="range" min={5} max={80} step={5} value={limit} onChange={(e) => onLimitChange(Number(e.target.value))} />
        </label>
      </section>
    </>
  );
}
