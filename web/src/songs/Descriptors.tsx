/**
 * Audio descriptors (AcousticBrainz).
 *
 * The song page shows them as a sound card: tempo (with a pulse at the
 * song's own beat), key and loudness as big numbers, then the mood profile as
 * an equalizer of columns. Probabilities are a magnitude per named quality, so
 * every column is one series color with its value in text above it: the
 * number, not the color, carries the reading, and a screen reader hears the
 * same text. `Meter` stays for the side-by-side song comparison.
 */
import {useId, type CSSProperties} from 'react';

import type {Schemas} from '../api/client';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

export const MOODS = [
  'danceable',
  'happy',
  'sad',
  'relaxed',
  'party',
  'aggressive',
  'acoustic',
  'electronic',
  'instrumental',
  'bright',
] as const;

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? '–'
    : `${Math.round(value * 100)}%`;
}

export function useDescribe() {
  const {t} = useI18n();
  return {
    tempo: (d: Schemas['AudioDescriptors'] | null | undefined) =>
      d?.bpm ? t('song.sound.bpm', {bpm: Math.round(d.bpm)}) : '–',
    key: (d: Schemas['AudioDescriptors'] | null | undefined) =>
      d?.key && d.scale
        ? t(`song.sound.key.${d.scale}` as MessageId, {key: d.key})
        : '–',
    length: (d: Schemas['AudioDescriptors'] | null | undefined) =>
      d?.lengthS
        ? t('song.sound.duration', {
            minutes: Math.floor(d.lengthS / 60),
            seconds: String(Math.round(d.lengthS % 60)).padStart(2, '0'),
          })
        : '–',
  };
}

export function Meter({label, value}: {label: string; value: number}) {
  return (
    <div className="meter">
      <span className="meter__label">{label}</span>
      <span className="meter__track" aria-hidden="true">
        <span className="meter__fill" style={{inlineSize: percent(value)}} />
      </span>
      <span className="meter__value">{percent(value)}</span>
    </div>
  );
}

/** The moods present, in catalog order, with the strongest ones marked. */
export function moodProfile(
  moods: Record<string, number>,
): {mood: (typeof MOODS)[number]; value: number; strong: boolean}[] {
  const present = MOODS.filter(m => typeof moods[m] === 'number').map(m => ({
    mood: m,
    value: Math.min(1, Math.max(0, moods[m]!)),
  }));
  const ranked = [...present].sort((a, b) => b.value - a.value);
  const strong = new Set(
    ranked
      .slice(0, 2)
      .filter(entry => entry.value >= 0.5)
      .map(entry => entry.mood),
  );
  return present.map(entry => ({...entry, strong: strong.has(entry.mood)}));
}

/** Seconds per beat, for the tempo pulse; null when the tempo is unknown or implausible. */
export function beatSeconds(bpm: number | null | undefined): number | null {
  if (!bpm || bpm < 30 || bpm > 300) return null;
  return Math.round((60 / bpm) * 1000) / 1000;
}

/** One recording's sound: tempo, key, loudness, then the mood equalizer. */
export function SoundProfile({
  descriptors,
}: {
  descriptors: Schemas['AudioDescriptors'];
}) {
  const {t} = useI18n();
  const describe = useDescribe();
  const captionId = useId();
  const beat = beatSeconds(descriptors.bpm);
  const profile = moodProfile(descriptors.moods);
  return (
    <div className="sound">
      <dl className="sound__facts">
        <div className="sound__fact sound__fact--tempo">
          <dt>{t('song.sound.tempo')}</dt>
          <dd>
            {beat !== null && (
              <span
                className="sound__pulse"
                style={{'--beat': `${beat}s`} as CSSProperties}
                aria-hidden="true"
              />
            )}
            {describe.tempo(descriptors)}
          </dd>
        </div>
        <div className="sound__fact">
          <dt>{t('song.sound.keyLabel')}</dt>
          <dd>{describe.key(descriptors)}</dd>
        </div>
        <div className="sound__fact">
          <dt>{t('song.sound.loudness')}</dt>
          <dd>{percent(descriptors.averageLoudness)}</dd>
        </div>
      </dl>
      {profile.length > 0 && (
        <figure className="eq" aria-labelledby={captionId}>
          <figcaption id={captionId} className="eq__caption">
            {t('song.sound.moods')}
          </figcaption>
          <ul className="eq__bars">
            {profile.map(({mood, value, strong}) => (
              <li
                key={mood}
                className="eq__item"
                data-strong={strong || undefined}
                style={{'--v': value} as CSSProperties}
              >
                <span className="eq__label">
                  {t(`song.mood.${mood}` as MessageId)}
                </span>
                <span className="eq__track" aria-hidden="true">
                  <span className="eq__fill" />
                </span>
                <span className="eq__value">{percent(value)}</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      <a
        className="sound__source"
        href={descriptors.source.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t('song.sound.source')}
      </a>
    </div>
  );
}
