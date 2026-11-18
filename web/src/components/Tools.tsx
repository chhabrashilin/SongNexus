/** The things you can do, as compact rows: an icon tile, a name, one line of what it does. */
import type {CSSProperties} from 'react';
import {Link} from 'react-router';

import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';

import {Icon, type IconName} from './Icon';

export interface Tool {
  id: string;
  to: string;
  icon: IconName;
  title: MessageId;
  body: MessageId;
  /** Kill-switch flag from /v1/config; the tool is hidden when it is off. */
  flag?: string;
}

/** Tile colors, spread around the wheel so neighbors differ. */
const BENTO_HUES = [350, 262, 205, 158, 28, 312, 190, 45];

export const TOOLS: Record<string, Tool> = {
  web: {
    id: 'web',
    to: '/explore',
    icon: 'explore',
    title: 'tool.web.title',
    body: 'tool.web.body',
    flag: 'explore',
  },
  path: {
    id: 'path',
    to: '/six-degrees',
    icon: 'route',
    title: 'tool.path.title',
    body: 'tool.path.body',
    flag: 'sixDegrees',
  },
  compare: {
    id: 'compare',
    to: '/compare',
    icon: 'compare',
    title: 'tool.compare.title',
    body: 'tool.compare.body',
    flag: 'compare',
  },
  songs: {
    id: 'songs',
    to: '/compare/songs',
    icon: 'note',
    title: 'tool.songs.title',
    body: 'tool.songs.body',
    flag: 'compare',
  },
  puzzle: {
    id: 'puzzle',
    to: '/play',
    icon: 'puzzle',
    title: 'tool.puzzle.title',
    body: 'tool.puzzle.body',
    flag: 'play',
  },
  games: {
    id: 'games',
    to: '/games',
    icon: 'puzzle',
    title: 'tool.games.title',
    body: 'tool.games.body',
    flag: 'play',
  },
  stories: {
    id: 'stories',
    to: '/stories',
    icon: 'movie',
    title: 'tool.stories.title',
    body: 'tool.stories.body',
    flag: 'stories',
  },
  around: {
    id: 'around',
    to: '/around-you',
    icon: 'place',
    title: 'tool.around.title',
    body: 'tool.around.body',
    flag: 'community',
  },
  library: {
    id: 'library',
    to: '/library',
    icon: 'library',
    title: 'tool.library.title',
    body: 'tool.library.body',
  },
  friends: {
    id: 'friends',
    to: '/friends',
    icon: 'people',
    title: 'tool.friends.title',
    body: 'tool.friends.body',
    flag: 'friends',
  },
};

export function ToolGrid({
  tools,
  flags,
}: {
  tools: Tool[];
  flags: Record<string, boolean>;
}) {
  const {t} = useI18n();
  return (
    <ul className="tool-grid">
      {tools
        .filter(tool => !tool.flag || flags[tool.flag] !== false)
        .map((tool, index) => (
          <li key={tool.id}>
            <Link className="tool-row" to={tool.to}>
              <span className="tool-row__icon" data-tone={index % 6}>
                <Icon name={tool.icon} />
              </span>
              <span className="tool-row__text">
                <span className="tool-row__title">{t(tool.title)}</span>
                <span className="tool-row__body">{t(tool.body)}</span>
              </span>
              <Icon name="chevron" size={20} />
            </Link>
          </li>
        ))}
    </ul>
  );
}

/**
 * Which tiles are double width in the four-column layout: the first two, and
 * the last two when they would otherwise leave half a row empty.
 */
function wide(index: number, count: number): boolean {
  if (index < 2) return true;
  return (count - 2) % 4 === 2 && index >= count - 2;
}

/** The same tools as tiles of different weight, for Home. */
export function Bento({
  tools,
  flags,
}: {
  tools: Tool[];
  flags: Record<string, boolean>;
}) {
  const {t} = useI18n();
  const shown = tools.filter(tool => !tool.flag || flags[tool.flag] !== false);
  return (
    <ul className="bento stagger">
      {shown.map((tool, index) => (
        <li
          key={tool.id}
          data-span={wide(index, shown.length) ? 2 : undefined}
          style={{'--i': index} as CSSProperties}
        >
          <Link
            className="bento__tile"
            to={tool.to}
            style={
              {'--hue': BENTO_HUES[index % BENTO_HUES.length]} as CSSProperties
            }
          >
            <span className="bento__icon">
              <Icon name={tool.icon} />
            </span>
            <span className="bento__title">{t(tool.title)}</span>
            <span className="bento__body">{t(tool.body)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
