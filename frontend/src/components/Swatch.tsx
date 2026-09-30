import type { Encoding } from "../utils/format";

/** A short line sample showing a connection type's color *and* dash pattern. */
export function Swatch({ encoding, title }: { encoding: Encoding; title?: string }) {
  return (
    <svg className="swatch" width="18" height="10" viewBox="0 0 18 10" role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <line
        x1="1"
        y1="5"
        x2="17"
        y2="5"
        stroke={encoding.color}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={encoding.dash ?? undefined}
      />
    </svg>
  );
}
