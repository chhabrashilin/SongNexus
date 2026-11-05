/**
 * Audio descriptors (AcousticBrainz) shown in words and thin meters.
 *
 * Probabilities are a magnitude per named quality, so each gets a thin meter in
 * the one series color with its value in text beside it: the number, not the
 * color, carries the reading, and a screen reader hears the same text.
 */
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

/** One recording's descriptors: tempo, key, length, then the mood profile. */
export function SoundProfile({
  descriptors,
}: {
  descriptors: Schemas['AudioDescriptors'];
}) {
  const {t} = useI18n();
  const describe = useDescribe();
  return (
    <div className="stack" style={{gap: 'var(--space-3)'}}>
      <dl className="facts">
        <div>
          <dt>{t('song.sound.tempo')}</dt>
          <dd>{describe.tempo(descriptors)}</dd>
        </div>
        <div>
          <dt>{t('song.sound.keyLabel')}</dt>
          <dd>{describe.key(descriptors)}</dd>
        </div>
        <div>
          <dt>{t('song.sound.loudness')}</dt>
          <dd>{percent(descriptors.averageLoudness)}</dd>
        </div>
      </dl>
      <div className="stack" style={{gap: 'var(--space-1)'}}>
        {MOODS.filter(m => descriptors.moods[m] !== undefined).map(m => (
          <Meter
            key={m}
            label={t(`song.mood.${m}` as MessageId)}
            value={descriptors.moods[m]!}
          />
        ))}
      </div>
      <a
        href={descriptors.source.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t('song.sound.source')}
      </a>
    </div>
  );
}
