import {describe, expect, it} from 'vitest';

import {createI18n} from '../i18n/i18n';
import {messages, type MessageId} from '../i18n/messages';

import {
  answerMessage,
  answerText,
  answerValues,
  destinationLabel,
  readsLikeQuestion,
  yearLabel,
  type AskIntent,
} from './ask';

const {t} = createI18n('en-US');
const list = (items: string[]) =>
  new Intl.ListFormat('en-US', {style: 'long', type: 'conjunction'}).format(
    items,
  );

describe('readsLikeQuestion', () => {
  it.each([
    'how is Kendrick Lamar connected to Daft Punk',
    'Who produced HUMBLE.',
    'Kendrick Lamar vs SZA',
    'Kendrick → SZA',
    'Kendrick Lamar collaborators',
    'artists similar to Björk',
    'anything ending with a question mark?',
    'four words make a question',
  ])('treats %j as a question', text => {
    expect(readsLikeQuestion(text)).toBe(true);
  });

  it.each([
    '',
    '   ',
    'Kendrick Lamar',
    'humble',
    '방탄소년단',
    'beyonce',
    'The Weeknd',
  ])('treats %j as a name', text => {
    expect(readsLikeQuestion(text)).toBe(false);
  });
});

describe('answers', () => {
  it('words a path from our data', () => {
    expect(
      answerText(
        {
          messageId: 'ask.answer.path',
          params: {a: 'Kendrick Lamar', b: 'Daft Punk', steps: 2},
        },
        list,
        t,
      ),
    ).toBe('Kendrick Lamar and Daft Punk are 2 steps apart in our data.');
  });

  it('joins names and counts the rest', () => {
    const values = answerValues(
      {names: ['A', 'B', 'C'], more: 74, artist: 'X', count: 77},
      list,
      t,
    );
    expect(values.names).toBe('A, B, C, and 74 others');
    expect(
      answerText(
        {
          messageId: 'ask.answer.song.FEATURED',
          params: {song: 'Money Trees', names: ['Jay Rock'], count: 1, more: 0},
        },
        list,
        t,
      ),
    ).toBe('Jay Rock is featured on “Money Trees”');
  });

  it('reads an unknown message ID as not understood', () => {
    expect(answerMessage('ask.answer.fromTheFuture')).toBe(
      'ask.answer.unknown',
    );
    expect(answerMessage('ask.answer.path')).toBe('ask.answer.path');
  });

  it('has wording for every message the server sends', () => {
    const server = [
      'path',
      'pathDirect',
      'pathNone',
      'pathLimit',
      'sameArtist',
      'compare',
      'compareSongs',
      'connections',
      'connections.none',
      'lookup.artist',
      'lookup.song',
      'nothing',
      'notFound',
      'ambiguous',
      'genreNotFound',
      'unknown',
      ...['PRODUCER', 'FEATURED', 'PERFORMER', 'ALL'].flatMap(r => [
        `song.${r}`,
        `song.${r}.none`,
      ]),
      ...[
        'ANY',
        'FEATURE',
        'PRODUCTION',
        'PRODUCED_BY',
        'PRODUCED_FOR',
        'CO_PRODUCED',
        'BAND',
        'CREDIT',
      ].flatMap(v => [`collab.${v}`, `collab.${v}.none`]),
    ];
    for (const id of server)
      expect(messages).toHaveProperty(`ask.answer.${id}`);
    const intents: AskIntent[] = [
      'FIND_PATH',
      'COMPARE_ARTISTS',
      'COMPARE_SONGS',
      'SONG_CREDITS',
      'COLLABORATORS',
      'CONNECTIONS',
      'LOOKUP',
      'UNKNOWN',
    ];
    for (const intent of intents) {
      expect(messages).toHaveProperty(destinationLabel(intent) as MessageId);
    }
  });

  it('labels year ranges', () => {
    expect(yearLabel(2010, 2019, t)).toBe('2010–2019');
    expect(yearLabel(2015, 2015, t)).toBe('2015');
    expect(yearLabel(2018, null, t)).toBe('Since 2018');
    expect(yearLabel(null, 2000, t)).toBe('Up to 2000');
    expect(yearLabel(null, undefined, t)).toBeNull();
  });
});
