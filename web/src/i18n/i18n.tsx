/**
 * Message formatting (ICU), locale and direction.
 *
 * R1 ships en-US plus two pseudo-locales for testing (plan §10):
 *   en-XA  accented and ~40% longer text, to catch truncation and hard-coded strings;
 *   ar-XB  right-to-left, to catch layout that ignores direction.
 * Choose one with ?locale=en-XA (remembered for the session).
 */
import {IntlMessageFormat} from 'intl-messageformat';
import {createContext, useContext, useMemo, type ReactNode} from 'react';

import {messages, type MessageId} from './messages';

export type Locale = 'en-US' | 'en-XA' | 'ar-XB';
type Values = Record<string, string | number | boolean | null | undefined>;

export interface I18n {
  locale: Locale;
  dir: 'ltr' | 'rtl';
  t: (id: MessageId, values?: Values) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
}

const ACCENTED: Record<string, string> = {
  a: 'á',
  e: 'é',
  i: 'í',
  o: 'ó',
  u: 'ú',
  c: 'ç',
  n: 'ñ',
  y: 'ý',
  A: 'Á',
  E: 'É',
  I: 'Í',
  O: 'Ó',
  U: 'Ú',
  C: 'Ç',
  N: 'Ñ',
  Y: 'Ý',
};

/** Pseudo-localizes literal text in an ICU pattern, leaving {placeholders} intact. */
export function pseudoLocalize(pattern: string): string {
  let depth = 0;
  let out = '';
  for (const ch of pattern) {
    if (ch === '{') depth++;
    if (ch === '}') depth--;
    out += depth === 0 ? (ACCENTED[ch] ?? ch) : ch;
  }
  const padding = '·'.repeat(Math.ceil(pattern.length * 0.4));
  return `⟦${out}${padding}⟧`;
}

function patternFor(locale: Locale, id: MessageId): string {
  const base: string = messages[id];
  return locale === 'en-XA' ? pseudoLocalize(base) : base;
}

export function createI18n(locale: Locale): I18n {
  const formatLocale =
    locale === 'en-US' ? 'en-US' : locale === 'ar-XB' ? 'ar' : 'en';
  const cache = new Map<MessageId, IntlMessageFormat>();
  const numbers = new Map<string, Intl.NumberFormat>();
  return {
    locale,
    dir: locale === 'ar-XB' ? 'rtl' : 'ltr',
    t(id, values) {
      let formatter = cache.get(id);
      if (!formatter) {
        formatter = new IntlMessageFormat(patternFor(locale, id), formatLocale);
        cache.set(id, formatter);
      }
      return String(formatter.format(values));
    },
    formatNumber(value, options) {
      const key = JSON.stringify(options ?? {});
      let formatter = numbers.get(key);
      if (!formatter) {
        formatter = new Intl.NumberFormat(formatLocale, options);
        numbers.set(key, formatter);
      }
      return formatter.format(value);
    },
  };
}

const LOCALES: readonly Locale[] = ['en-US', 'en-XA', 'ar-XB'];

/** Picks the locale from ?locale=, then the session, then en-US. */
export function detectLocale(
  search: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> | null,
): Locale {
  const requested = new URLSearchParams(search).get('locale');
  if (requested && (LOCALES as readonly string[]).includes(requested)) {
    storage?.setItem('songnexus.locale', requested);
    return requested as Locale;
  }
  const remembered = storage?.getItem('songnexus.locale');
  if (remembered && (LOCALES as readonly string[]).includes(remembered)) {
    return remembered as Locale;
  }
  return 'en-US';
}

const I18nContext = createContext<I18n>(createI18n('en-US'));

export function I18nProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: ReactNode;
}) {
  const value = useMemo(() => createI18n(locale), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  return useContext(I18nContext);
}
