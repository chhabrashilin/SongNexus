/** Guided music companion. The catalog actions are intentionally explicit. */
import {useState} from 'react';
import {Link} from 'react-router';
import type {FormEvent} from 'react';

import {usePageTitle} from '../app/Shell';
import {Icon} from '../components/Icon';
import {useI18n} from '../i18n/i18n';

type Reply = {question: string; answer: string; to: string};

export function GuideScreen() {
  const {t} = useI18n();
  const [question, setQuestion] = useState('');
  const [reply, setReply] = useState<Reply | null>(null);
  usePageTitle(t('guide.title'));

  function ask(value: string) {
    const normalized = value.toLowerCase();
    const isSongs = normalized.includes('song') || normalized.includes('sound');
    const isPath =
      normalized.includes('connect') ||
      normalized.includes('path') ||
      normalized.includes('artist');
    const to = isSongs
      ? '/compare/songs'
      : isPath
        ? '/six-degrees'
        : '/discover';
    const answer = isSongs
      ? t('guide.reply.songs')
      : isPath
        ? t('guide.reply.path')
        : t('guide.reply.discover');
    setReply({question: value, answer, to});
    setQuestion('');
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = question.trim();
    if (value) ask(value);
  }

  return (
    <div className="stack product-screen">
      <section className="product-hero guide-hero stack">
        <span className="product-hero__icon" aria-hidden="true">
          <Icon name="spark" />
        </span>
        <p className="product-hero__label">{t('nav.guide')}</p>
        <h1>{t('guide.title')}</h1>
        <p className="muted">{t('guide.lead')}</p>
        <form className="guide-form" onSubmit={submit}>
          <label htmlFor="guide-question">{t('guide.inputLabel')}</label>
          <div className="field">
            <input
              id="guide-question"
              value={question}
              onChange={event => setQuestion(event.target.value)}
              placeholder={t('guide.inputPlaceholder')}
            />
            <button className="btn btn--filled" type="submit">
              {t('guide.ask')}
            </button>
          </div>
        </form>
      </section>

      {reply && (
        <section className="guide-thread card" aria-live="polite">
          <p className="guide-thread__question">{reply.question}</p>
          <p>{reply.answer}</p>
          <Link className="btn btn--tonal" to={reply.to}>
            {t('action.showMore')}
          </Link>
        </section>
      )}

      <section className="section">
        <h2>{t('guide.suggestions')}</h2>
        <div className="suggestion-grid">
          <button
            className="suggestion-card"
            type="button"
            onClick={() => ask(t('guide.suggestion.path'))}
          >
            {t('guide.suggestion.path')}
          </button>
          <button
            className="suggestion-card"
            type="button"
            onClick={() => ask(t('guide.suggestion.songs'))}
          >
            {t('guide.suggestion.songs')}
          </button>
          <button
            className="suggestion-card"
            type="button"
            onClick={() => ask(t('guide.suggestion.discover'))}
          >
            {t('guide.suggestion.discover')}
          </button>
        </div>
      </section>
    </div>
  );
}

export default GuideScreen;
