import type { Category } from "../types/api";

/**
 * Visual encoding of connection types.
 *
 * Any two types can meet in the graph, so the palette must separate *all* pairs,
 * and only three categorical hues pass that check in both themes (validated with
 * the dataviz palette validator: worst CVD ΔE 9.2 light / 9.4 dark, normal-vision
 * ΔE ≥ 20.9). The three most common types get those hues; the rest are neutral
 * lines told apart by dash pattern, so identity never depends on color alone.
 */
export interface Encoding {
  color: string;
  dash: string | null;
}

export const CATEGORY_ENCODING: Record<Category, Encoding> = {
  performance: { color: "var(--series-1)", dash: null },
  production: { color: "var(--series-2)", dash: null },
  contribution: { color: "var(--series-3)", dash: null },
  membership: { color: "var(--neutral-strong)", dash: null },
  sampling: { color: "var(--neutral-strong)", dash: "6 4" },
  engineering: { color: "var(--neutral-soft)", dash: "2 4" },
};

/** Evidence kind (backend) -> user-facing category. */
export const KIND_CATEGORY: Record<string, Category> = {
  performed_with: "performance",
  produced_for: "production",
  co_produced: "production",
  contributed_to: "contribution",
  sampled: "sampling",
  engineered: "engineering",
  member_of: "membership",
  collaboration: "membership",
  supported: "membership",
  taught: "membership",
};

export function kindEncoding(kind: string): Encoding {
  const category = KIND_CATEGORY[kind];
  return category ? CATEGORY_ENCODING[category] : { color: "var(--neutral-soft)", dash: null };
}

export const CATEGORY_LABELS: Record<Category, string> = {
  performance: "Performed together",
  production: "Production",
  contribution: "Contributions",
  sampling: "Samples",
  membership: "Bands & memberships",
  engineering: "Engineering",
};

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function initials(name: string): string {
  const words = name.replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "")).toUpperCase() || "?";
}
