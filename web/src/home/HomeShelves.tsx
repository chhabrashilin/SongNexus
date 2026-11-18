/**
 * Shelves the catalog surfaces for Home: the people behind the hits, the most
 * connected artists, what came out on this day, genres, decades and labels.
 *
 * The server computes them from credits (`GET /v1/shelves`) and sends a reason
 * with every item ("Produced 96 recordings"); the wording lives here. Home
 * stands without them: nothing renders while loading fails or the list is empty.
 */
import {useQuery} from '@tanstack/react-query';
import {Link} from 'react-router';

import {api, idOf, unwrap, type Schemas} from '../api/client';
import {artistPath, imageOf} from '../components/ArtistRow';
import {CoverCard, Shelf} from '../components/Shelf';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {localDate} from '../play/game';

import {curate, shelfDate} from './shelves';

type ShelfData = Schemas['Shelf'];
type Item = Schemas['ShelfItem'];

const HOUR = 60 * 60_000;

function useShelves(date: string) {
  return useQuery({
    queryKey: ['shelves', date],
    queryFn: () => unwrap(api.GET('/v1/shelves', {params: {query: {date}}})),
    staleTime: HOUR,
    gcTime: 2 * HOUR,
    retry: false,
  });
}

function ShelfCard({item, rank}: {item: Item; rank: number}) {
  const {t} = useI18n();
  const reason = t(
    item.reason.messageId as MessageId,
    item.reason.params as Record<string, string | number>,
  );
  const badge = rank < 3 ? `#${rank + 1}` : undefined;
  if (item.artist)
    return (
      <CoverCard
        to={artistPath(item.artist)}
        title={item.artist.displayName}
        subtitle={reason}
        image={imageOf(item.artist)}
        badge={badge}
        round
      />
    );
  if (item.recording) {
    const lead = item.recording.artists[0];
    return (
      <CoverCard
        to={`/song/${idOf(item.recording.name)}`}
        title={item.recording.displayName}
        subtitle={[lead?.displayName, reason].filter(Boolean).join(' · ')}
        image={imageOf(lead)}
      />
    );
  }
  if (item.label)
    return (
      <CoverCard
        to={`/label/${idOf(item.label.name)}`}
        title={item.label.displayName}
        subtitle={reason}
        badge={badge}
      />
    );
  return null;
}

function HomeShelf({shelf, today}: {shelf: ShelfData; today: string}) {
  const {t, locale} = useI18n();
  const params = shelf.params as Record<string, string | number>;
  const title = t(shelf.messageId as MessageId, params);
  const eyebrow =
    shelf.kind === 'ON_THIS_DAY'
      ? new Intl.DateTimeFormat(locale, {
          month: 'long',
          day: 'numeric',
        }).format(shelfDate(today))
      : t(`shelf.eyebrow.${shelf.kind}` as MessageId);
  // Rankings read as rankings: the first three carry their place.
  const ranked = shelf.kind !== 'ON_THIS_DAY';
  return (
    <Shelf
      title={title}
      eyebrow={eyebrow}
      action={
        shelf.genre ? (
          <Link
            className="btn btn--outlined btn--compact"
            to={`/genre/${idOf(shelf.genre)}`}
          >
            {t('action.showMore')}
          </Link>
        ) : undefined
      }
    >
      {shelf.items.map((item, index) => (
        <ShelfCard
          key={item.artist?.name ?? item.recording?.name ?? item.label?.name}
          item={item}
          rank={ranked ? index : Infinity}
        />
      ))}
    </Shelf>
  );
}

export function HomeShelves() {
  const today = localDate();
  const shelves = useShelves(today);
  const shown = curate(shelves.data?.shelves ?? []);
  return (
    <>
      {shown.map(shelf => (
        <HomeShelf key={shelf.name} shelf={shelf} today={today} />
      ))}
    </>
  );
}
