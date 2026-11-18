/**
 * Countries for the Around you picker, named in the listener's language by the
 * browser (Intl.DisplayNames), so the list needs no catalog of its own.
 */

/** Region codes that aren't countries (groupings, reserved and pseudo codes). */
const NOT_COUNTRIES = new Set([
  'AC',
  'CP',
  'DG',
  'EA',
  'EU',
  'EZ',
  'IC',
  'QO',
  'TA',
  'UN',
  'XA',
  'XB',
  'ZZ',
]);

export interface Country {
  code: string;
  name: string;
}

const cache = new Map<string, Country[]>();

/** Every ISO 3166 country the browser can name, sorted by name in `locale`. */
export function countryOptions(locale: string): Country[] {
  const cached = cache.get(locale);
  if (cached) return cached;
  let names: Intl.DisplayNames;
  try {
    names = new Intl.DisplayNames([locale, 'en'], {
      type: 'region',
      fallback: 'none',
    });
  } catch {
    return [];
  }
  const out: Country[] = [];
  for (let a = 65; a <= 90; a++)
    for (let b = 65; b <= 90; b++) {
      const code = String.fromCharCode(a, b);
      if (NOT_COUNTRIES.has(code)) continue;
      let name: string | undefined;
      try {
        name = names.of(code);
      } catch {
        name = undefined;
      }
      if (name && name !== code) out.push({code, name});
    }
  out.sort((x, y) => x.name.localeCompare(y.name, locale));
  cache.set(locale, out);
  return out;
}

/** The name of one country code, or the code itself when the browser can't name it. */
export function countryName(code: string, locale: string): string {
  try {
    return (
      new Intl.DisplayNames([locale, 'en'], {type: 'region'}).of(code) ?? code
    );
  } catch {
    return code;
  }
}
