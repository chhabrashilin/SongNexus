/**
 * Friend paths: "How are your top artists connected to mine?" The shortest
 * paths between your top artists and a friend's, as portrait chains with the
 * credits one tap away, plus the artists and collaborators you share.
 *
 * Both people must share their top artists (off by default); when one doesn't,
 * the page says whose sharing is off and what to do, without guessing why.
 */
import {useMemo, useState, type CSSProperties} from 'react';
import {Link} from 'react-router';

import {ApiError, type ArtistSummary} from '../api/client';
import {
  useFriendPaths,
  useShareTopArtists,
  type FriendPath,
  type FriendPaths as Paths,
} from '../api/personal';
import {artistPath, imageOf} from '../components/ArtistRow';
import {EvidenceList} from '../components/ConnectionSheet';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Cover} from '../components/Shelf';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';

import {PortraitChain, PortraitStack} from './Chain';

/** Paths shown before "Show all". */
const PATHS = 3;

type Step = FriendPath['steps'][number];

/** The artists along a path, in order (the start, then each step's end). */
export function pathArtists(path: FriendPath): ArtistSummary[] {
  if (path.steps.length === 0) return [path.fromArtist, path.toArtist];
  return [path.steps[0]!.fromArtist, ...path.steps.map(s => s.toArtist)];
}

/** Display names for every artist the response mentions, by resource name. */
export function namesOf(data: Paths): Map<string, string> {
  const names = new Map<string, string>();
  const add = (a: ArtistSummary) => names.set(a.name, a.displayName);
  data.viewerArtists.forEach(add);
  data.friendArtists.forEach(add);
  data.sharedArtists.forEach(add);
  data.sharedCollaborators.forEach(c => add(c.artist));
  for (const path of data.paths)
    path.steps.forEach(s => (add(s.fromArtist), add(s.toArtist)));
  return names;
}

function Refusal({error, friend}: {error: unknown; friend: string}) {
  const {t} = useI18n();
  const snackbar = useSnackbar();
  const share = useShareTopArtists();
  if (!(error instanceof ApiError)) return <ErrorState error={error} />;
  const side = error.metadata.side;
  if (error.reason === 'VIEWER_NOT_SHARING')
    return (
      <div className="paths-note">
        <Icon name="lock" />
        <div className="paths-note__text">
          <p className="paths-note__title">{t('paths.viewerOff.title')}</p>
          <p>{t('paths.viewerOff.body')}</p>
          <button
            type="button"
            className="btn btn--filled"
            disabled={share.isPending}
            onClick={() =>
              share.mutate(true, {
                onSuccess: () => snackbar(t('paths.sharing.on')),
                onError: () => snackbar(t('state.error.title')),
              })
            }
          >
            <Icon name="people" />
            {t('paths.viewerOff.action')}
          </button>
        </div>
      </div>
    );
  if (error.reason === 'FRIEND_NOT_SHARING')
    return (
      <div className="paths-note">
        <Icon name="lock" />
        <div className="paths-note__text">
          <p className="paths-note__title">
            {t('paths.friendOff.title', {name: friend})}
          </p>
          <p>{t('paths.friendOff.body', {name: friend})}</p>
        </div>
      </div>
    );
  if (error.reason === 'NO_TOP_ARTISTS')
    return (
      <div className="paths-note">
        <Icon name="note" />
        <div className="paths-note__text">
          {side === 'friend' ? (
            <>
              <p className="paths-note__title">
                {t('paths.friendEmpty.title', {name: friend})}
              </p>
              <p>{t('paths.friendEmpty.body', {name: friend})}</p>
            </>
          ) : (
            <>
              <p className="paths-note__title">
                {t('paths.viewerEmpty.title')}
              </p>
              <p>{t('paths.viewerEmpty.body')}</p>
              <div className="row">
                <Link className="btn btn--tonal" to="/you">
                  {t('paths.viewerEmpty.top5')}
                </Link>
                <Link className="btn btn--text" to="/library">
                  {t('paths.viewerEmpty.connect')}
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    );
  return <ErrorState error={error} />;
}

function PathCard({
  path,
  index,
  onStep,
}: {
  path: FriendPath;
  index: number;
  onStep: (step: Step) => void;
}) {
  const {t} = useI18n();
  const artists = pathArtists(path);
  const from = path.fromArtist.displayName;
  const to = path.toArtist.displayName;
  return (
    <li className="path-card" style={{'--i': index} as CSSProperties}>
      <p className="path-card__head">
        <span className="path-card__steps">
          {t('paths.steps', {count: path.steps.length})}
        </span>
        <span className="path-card__ends">
          <bdi>{from}</bdi>
          <Icon name="swap" size={16} />
          <bdi>{to}</bdi>
        </span>
      </p>
      <PortraitChain
        artists={artists}
        label={t('paths.chainLabel', {from, to})}
        links={path.steps.map(step => ({
          text: t('paths.credits', {count: step.evidence.length}),
          label: t('paths.creditsLabel', {
            a: step.fromArtist.displayName,
            b: step.toArtist.displayName,
          }),
          onOpen: () => onStep(step),
        }))}
      />
    </li>
  );
}

function Loaded({data, friend}: {data: Paths; friend: string}) {
  const {t} = useI18n();
  const [all, setAll] = useState(false);
  const [step, setStep] = useState<Step | null>(null);
  const names = useMemo(() => namesOf(data), [data]);
  const byName = useMemo(
    () =>
      new Map(
        [...data.viewerArtists, ...data.friendArtists].map(a => [a.name, a]),
      ),
    [data],
  );
  const paths = all ? data.paths : data.paths.slice(0, PATHS);

  return (
    <div className="paths">
      {data.demoData && (
        <p className="demo-note" role="note">
          <Icon name="info" />
          <span>{t('paths.demo', {name: friend})}</span>
        </p>
      )}

      <div className="paths__head">
        <div className="paths__side">
          <PortraitStack artists={data.viewerArtists} />
          <span className="paths__who">{t('paths.yours')}</span>
          <span className="paths__names">
            <bdi>
              {data.viewerArtists
                .slice(0, 3)
                .map(a => a.displayName)
                .join(', ')}
            </bdi>
          </span>
        </div>
        <div className="paths__score">
          <span className="paths__count">{data.paths.length}</span>
          <span className="paths__count-label">
            {t('paths.found', {count: data.paths.length})}
          </span>
        </div>
        <div className="paths__side">
          <PortraitStack artists={data.friendArtists} />
          <span className="paths__who">
            {t('paths.theirs', {name: friend})}
          </span>
          <span className="paths__names">
            <bdi>
              {data.friendArtists
                .slice(0, 3)
                .map(a => a.displayName)
                .join(', ')}
            </bdi>
          </span>
        </div>
      </div>

      {data.sharedArtists.length > 0 && (
        <div className="paths__shared">
          <h3 className="paths__sub">
            {t('paths.shared', {count: data.sharedArtists.length})}
          </h3>
          <ul className="paths__shared-list">
            {data.sharedArtists.map(artist => (
              <li key={artist.name}>
                <Link className="chip chip--artist" to={artistPath(artist)}>
                  <Cover
                    name={artist.displayName}
                    image={imageOf(artist)}
                    round
                  />
                  <bdi>{artist.displayName}</bdi>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.paths.length === 0 ? (
        <p className="quiet-note">
          <Icon name="route" />
          <span>{t('paths.none', {name: friend})}</span>
        </p>
      ) : (
        <>
          <ol className="path-cards stagger">
            {paths.map((path, i) => (
              <PathCard
                key={`${path.fromArtist.name}-${path.toArtist.name}`}
                path={path}
                index={i}
                onStep={setStep}
              />
            ))}
          </ol>
          {data.paths.length > PATHS && (
            <button
              type="button"
              className="btn btn--outlined paths__all"
              aria-expanded={all}
              onClick={() => setAll(value => !value)}
            >
              {all
                ? t('paths.fewer')
                : t('paths.all', {count: data.paths.length})}
            </button>
          )}
        </>
      )}

      {data.sharedCollaborators.length > 0 && (
        <div className="paths__collabs">
          <h3 className="paths__sub">{t('paths.collaborators')}</h3>
          <p className="muted">
            {t('paths.collaborators.body', {name: friend})}
          </p>
          <ol className="rank-grid stagger">
            {data.sharedCollaborators.slice(0, 6).map((c, i) => (
              <li key={c.artist.name} style={{'--i': i} as CSSProperties}>
                <Link className="rank-row" to={artistPath(c.artist)}>
                  <Cover
                    name={c.artist.displayName}
                    image={imageOf(c.artist)}
                    round
                  />
                  <span className="rank-row__text">
                    <span className="rank-row__title">
                      <bdi>{c.artist.displayName}</bdi>
                    </span>
                    <span className="rank-row__sub">
                      <bdi>
                        {t('paths.collaborator.links', {
                          yours: c.viewerArtists
                            .map(n => byName.get(n)?.displayName ?? '')
                            .filter(Boolean)
                            .slice(0, 2)
                            .join(', '),
                          theirs: c.friendArtists
                            .map(n => byName.get(n)?.displayName ?? '')
                            .filter(Boolean)
                            .slice(0, 2)
                            .join(', '),
                        })}
                      </bdi>
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      )}

      <Sheet
        open={step !== null}
        title={
          step
            ? t('connection.evidenceTitle', {
                a: step.fromArtist.displayName,
                b: step.toArtist.displayName,
              })
            : ''
        }
        onClose={() => setStep(null)}
      >
        {step && (
          <>
            {step.track && (
              <p className="muted">
                {step.track.year
                  ? t('paths.trackYear', {
                      title: step.track.displayName,
                      year: String(step.track.year),
                    })
                  : t('paths.track', {title: step.track.displayName})}
              </p>
            )}
            <EvidenceList
              evidence={step.evidence}
              nameOf={n => names.get(n) ?? ''}
            />
          </>
        )}
      </Sheet>
    </div>
  );
}

export function FriendPaths({user, name}: {user: string; name: string}) {
  const {t} = useI18n();
  const paths = useFriendPaths(user);
  if (paths.isPending)
    return (
      <div className="paths-skeleton" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <span className="skeleton paths-skeleton__head" />
        <span className="skeleton paths-skeleton__row" />
        <span className="skeleton paths-skeleton__row" />
      </div>
    );
  if (paths.isError) return <Refusal error={paths.error} friend={name} />;
  return <Loaded data={paths.data} friend={name} />;
}
