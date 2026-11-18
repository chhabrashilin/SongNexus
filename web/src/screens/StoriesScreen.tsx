/**
 * Stories: connection stories generated from published credits, one at a time.
 *
 * Each story fills the viewer. Move between them by scrolling (it snaps), the
 * arrow keys, the buttons, tapping the sides or swiping sideways. The position
 * is in the address (`?story=`), so a story can be linked to. Nothing moves by
 * itself unless the listener presses play, and play can always be paused.
 * To assistive technology the viewer is an ordered list of articles.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import {Link, useSearchParams} from 'react-router';

import {useStories} from '../api/discover';
import {useAmbient} from '../app/ambient';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {EvidenceList} from '../components/ConnectionSheet';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {useSnackbar} from '../components/Snackbar';
import {ErrorState} from '../components/States';
import {useI18n} from '../i18n/i18n';
import type {MessageId} from '../i18n/messages';
import {
  artistNamer,
  findStory,
  orderedParts,
  stepForKey,
  storyId,
  storyLink,
  storyValues,
  swipeStep,
  type Story,
} from '../stories/stories';
import {StorySlide} from '../stories/StoryCard';

/** How long a story stays up when the listener presses play. */
const AUTOPLAY_MS = 9000;
/** How far to page through the feed looking for a linked story. */
const MAX_SEEK = 60;

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  );
}

export default function StoriesScreen() {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const enabled = flags.stories !== false;
  const query = useStories(enabled);
  usePageTitle(t('stories.title'));

  if (!enabled) return <StoriesOff />;
  if (query.isPending) return <StoriesSkeleton />;
  if (query.isError) {
    return (
      <StoriesFrame>
        <div className="story story--state">
          <ErrorState
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        </div>
      </StoriesFrame>
    );
  }
  const stories = query.data.pages.flatMap(p => p.stories);
  if (stories.length === 0) return <StoriesEmpty />;
  return (
    <StoriesViewer
      stories={stories}
      total={Math.max(query.data.pages[0]?.totalSize ?? 0, stories.length)}
      hasNextPage={query.hasNextPage}
      isFetchingNextPage={query.isFetchingNextPage}
      fetchNextPage={() => void query.fetchNextPage()}
    />
  );
}

/** The page around the viewer: the title, and for states, nothing else. */
function StoriesFrame({children}: {children: ReactNode}) {
  const {t} = useI18n();
  useAmbient(null);
  return (
    <div className="stories">
      <header className="stories__head">
        <div className="stories__titles">
          <p className="strapline">{t('stories.honest')}</p>
          <h1>{t('stories.title')}</h1>
        </div>
      </header>
      {children}
    </div>
  );
}

function StoriesSkeleton() {
  const {t} = useI18n();
  return (
    <StoriesFrame>
      <div className="stories__progress" aria-hidden="true">
        {Array.from({length: 6}, (_, i) => (
          <span key={i} className="stories__seg" />
        ))}
      </div>
      <div className="story story--skeleton" role="status">
        <span className="visually-hidden">{t('state.loading')}</span>
        <div className="story__stage" aria-hidden="true">
          <span className="skeleton story__skel-portrait" />
          <span className="skeleton story__skel-portrait story__skel-portrait--via" />
          <span className="skeleton story__skel-portrait" />
        </div>
        <div className="story__text" aria-hidden="true">
          <span className="skeleton story__skel-line story__skel-line--short" />
          <span className="skeleton story__skel-line story__skel-line--title" />
          <span className="skeleton story__skel-line story__skel-line--title" />
          <span className="skeleton story__skel-line story__skel-line--box" />
          <span className="skeleton story__skel-line story__skel-line--short" />
        </div>
      </div>
    </StoriesFrame>
  );
}

function StoriesEmpty() {
  const {t} = useI18n();
  return (
    <StoriesFrame>
      <div className="story story--state">
        <div className="story__state">
          <span className="story__state-icon" aria-hidden="true">
            <Icon name="movie" size={32} />
          </span>
          <p className="story__state-title">{t('stories.empty')}</p>
          <p className="story__state-body">{t('stories.empty.body')}</p>
          <div className="story__actions">
            <Link className="btn btn--filled" to="/explore">
              <Icon name="explore" />
              {t('stories.empty.action')}
            </Link>
          </div>
        </div>
      </div>
    </StoriesFrame>
  );
}

function StoriesOff() {
  const {t} = useI18n();
  useAmbient(null);
  return (
    <div className="stories">
      <div className="story story--state">
        <div className="story__state">
          <span className="story__state-icon" aria-hidden="true">
            <Icon name="movie" size={32} />
          </span>
          <h1 className="story__state-title">{t('stories.title')}</h1>
          <p className="story__state-body">{t('stories.off')}</p>
          <div className="story__actions">
            <Link className="btn btn--filled" to="/games">
              <Icon name="puzzle" />
              {t('stories.end.games')}
            </Link>
            <Link className="btn btn--tonal" to="/explore">
              {t('stories.empty.action')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function StoriesViewer({
  stories,
  total,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: {
  stories: Story[];
  total: number;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}) {
  const {t, dir} = useI18n();
  const snackbar = useSnackbar();
  const [search, setSearch] = useSearchParams();
  const root = useRef<HTMLDivElement>(null);
  const feed = useRef<HTMLOListElement>(null);
  const swipe = useRef<{x: number; y: number; id: number} | null>(null);
  const landed = useRef(false);
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [credits, setCredits] = useState<Story | null>(null);
  const count = stories.length;
  // The slide after the last story says so; it is index `count`.
  const atEnd = current >= count;
  const story = stories[Math.min(current, count - 1)]!;
  const param = search.get('story');
  useAmbient(
    atEnd ? null : (orderedParts(story)[0]?.artist.displayName ?? story.name),
  );

  const go = useCallback(
    (index: number, instant = false) => {
      const target = Math.max(0, Math.min(count, index));
      const list = feed.current;
      const slide = list?.querySelector<HTMLElement>(
        `[data-story-index="${target}"]`,
      );
      if (list && slide) {
        list.scrollTo({
          top: slide.offsetTop,
          behavior: instant || prefersReducedMotion() ? 'auto' : 'smooth',
        });
      }
      setCurrent(target);
    },
    [count],
  );
  const step = useCallback(
    (by: number) => {
      setPlaying(by > 0 && playing);
      go(current + by);
    },
    [current, go, playing],
  );

  // Land on a linked story, paging through the feed until it is loaded.
  useEffect(() => {
    if (landed.current) return;
    const found = findStory(stories, param);
    if (found === -1 && param && hasNextPage && count < MAX_SEEK) {
      if (!isFetchingNextPage) fetchNextPage();
      return;
    }
    landed.current = true;
    if (found > 0) go(found, true);
  }, [
    stories,
    param,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    count,
    go,
  ]);

  // Keep the address in step with the story shown.
  useEffect(() => {
    if (!landed.current || atEnd) return;
    const id = storyId(stories[current]!);
    if (search.get('story') === id || (!search.get('story') && current === 0))
      return;
    const next = new URLSearchParams(search);
    next.set('story', id);
    setSearch(next, {replace: true});
  }, [current, atEnd, stories, search, setSearch]);

  // Follow scrolling: the story mostly in view is the current one.
  useEffect(() => {
    const list = feed.current;
    if (!list) return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const i = Number((entry.target as HTMLElement).dataset.storyIndex);
          if (Number.isFinite(i)) setCurrent(i);
        }
      },
      {root: list, threshold: 0.6},
    );
    list
      .querySelectorAll('[data-story-index]')
      .forEach(el => observer.observe(el));
    return () => observer.disconnect();
  }, [count]);

  // Fetch the next page before the listener reaches the end.
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && current >= count - 2)
      fetchNextPage();
  }, [current, count, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Play: the next story after a while, until paused, a sheet opens or the end.
  useEffect(() => {
    if (!playing || credits) return;
    if (atEnd) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => go(current + 1), AUTOPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, credits, atEnd, current, go]);
  useEffect(() => {
    const pause = () => document.hidden && setPlaying(false);
    document.addEventListener('visibilitychange', pause);
    return () => document.removeEventListener('visibilitychange', pause);
  }, []);

  // Arrow keys work from anywhere on the page, not only inside the viewer.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey) return;
      if (event.metaKey || typing(event.target) || credits) return;
      const active = document.activeElement;
      const inside =
        active === document.body || (root.current?.contains(active) ?? false);
      if (!inside) return;
      const by = stepForKey(event.key, dir);
      if (!by) return;
      event.preventDefault();
      step(by);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dir, step, credits]);

  function onPointerDown(event: PointerEvent<HTMLOListElement>) {
    if (event.pointerType === 'mouse') return;
    swipe.current = {x: event.clientX, y: event.clientY, id: event.pointerId};
  }
  function onPointerUp(event: PointerEvent<HTMLOListElement>) {
    const start = swipe.current;
    swipe.current = null;
    if (!start || start.id !== event.pointerId) return;
    const by = swipeStep(event.clientX - start.x, event.clientY - start.y, dir);
    if (by) step(by);
  }

  async function share(s: Story) {
    const url = storyLink(window.location.origin, s);
    const title = t(s.messageId as MessageId, storyValues(s));
    try {
      if (navigator.share) await navigator.share({title, url});
      else {
        await navigator.clipboard.writeText(url);
        snackbar(t('stories.linkCopied'));
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError'))
        snackbar(t('stories.shareFailed'));
    }
  }

  const position = atEnd
    ? t('stories.end.title')
    : t('stories.card', {n: current + 1, total});

  return (
    <div className="stories" ref={root}>
      <header className="stories__head">
        <div className="stories__titles">
          <p className="strapline">{t('stories.honest')}</p>
          <h1>{t('stories.title')}</h1>
        </div>
        <div
          className="stories__controls glass"
          role="group"
          aria-label={t('stories.controls')}
        >
          <span className="stories__count" aria-hidden="true">
            {t('stories.count', {n: Math.min(current + 1, count), total})}
          </span>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setPlaying(p => !p)}
            disabled={atEnd}
          >
            <Icon
              name={playing ? 'pause' : 'play'}
              label={playing ? t('stories.pause') : t('stories.play')}
            />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-disabled={current === 0}
            onClick={() => current > 0 && step(-1)}
          >
            <Icon name="arrowUp" label={t('stories.previous')} />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-disabled={atEnd}
            onClick={() => !atEnd && step(1)}
          >
            <Icon name="arrowDown" label={t('stories.next')} />
          </button>
        </div>
      </header>

      <div className="stories__progress" aria-hidden="true">
        {Array.from({length: Math.min(total, MAX_SEEK)}, (_, i) => (
          <span
            key={i}
            className="stories__seg"
            data-state={
              i < current ? 'done' : i === current ? 'current' : undefined
            }
            data-playing={(i === current && playing && !credits) || undefined}
            style={{'--seg-ms': `${AUTOPLAY_MS}ms`} as CSSProperties}
          />
        ))}
      </div>

      <p className="visually-hidden" aria-live="polite">
        {position}
      </p>

      <ol
        ref={feed}
        className="stories__feed"
        aria-label={t('stories.feed')}
        // A scroll region: focusable so the keyboard reaches it without a pointer.
        tabIndex={0}
        onKeyDown={(event: ReactKeyboardEvent) => {
          // Handled by the page-level listener; keep the list from scrolling twice.
          if (stepForKey(event.key, dir) && !typing(event.target))
            event.preventDefault();
        }}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (swipe.current = null)}
      >
        {stories.map((s, i) => (
          <li
            key={s.name}
            className="stories__item"
            data-story-index={i}
            data-current={i === current || undefined}
          >
            <StorySlide
              story={s}
              index={i}
              total={total}
              near={Math.abs(i - current) <= 1}
              onStep={by => step(by)}
              onCredits={setCredits}
              onShare={s => void share(s)}
            />
          </li>
        ))}
        <li
          className="stories__item"
          data-story-index={count}
          data-current={atEnd || undefined}
        >
          <section className="story story--state" aria-labelledby="stories-end">
            <div className="story__state">
              {hasNextPage ? (
                <>
                  <p className="story__state-title" id="stories-end">
                    {t('stories.loadingMore')}
                  </p>
                  <button
                    type="button"
                    className="btn btn--tonal"
                    disabled={isFetchingNextPage}
                    onClick={fetchNextPage}
                  >
                    {t('stories.more')}
                  </button>
                </>
              ) : (
                <>
                  <span className="story__state-icon" aria-hidden="true">
                    <Icon name="check" size={32} />
                  </span>
                  <h2 className="story__state-title" id="stories-end">
                    {t('stories.end.title')}
                  </h2>
                  <p className="story__state-body">{t('stories.end')}</p>
                  <div className="story__actions">
                    <Link className="btn btn--filled" to="/games">
                      <Icon name="puzzle" />
                      {t('stories.end.games')}
                    </Link>
                    <button
                      type="button"
                      className="btn btn--tonal"
                      onClick={() => go(0)}
                    >
                      <Icon name="arrowUp" />
                      {t('stories.end.again')}
                    </button>
                  </div>
                </>
              )}
            </div>
          </section>
        </li>
      </ol>

      <p className="stories__hint">
        <Icon name="info" size={16} />
        {t('stories.keys')}
      </p>

      <Sheet
        open={credits !== null}
        title={t('stories.sheet.title')}
        onClose={() => setCredits(null)}
      >
        {credits && (
          <>
            <p className="stories__sheet-lead">
              <bdi>
                {t(credits.messageId as MessageId, storyValues(credits))}
              </bdi>
            </p>
            <EvidenceList
              evidence={credits.credits}
              nameOf={artistNamer(credits)}
            />
            <p className="muted">{t('stories.honest')}</p>
          </>
        )}
      </Sheet>
    </div>
  );
}
