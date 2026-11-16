/** The things you can do, as compact rows: an icon tile, a name, one line of what it does. */
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
