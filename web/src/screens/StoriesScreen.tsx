/**
 * Stories: a vertical, snap-scrolling feed of short connection stories generated
 * from published credits. Arrow keys and Page Up/Down move between stories.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';

import {useStories} from '../api/discover';
import {useConfigFlags} from '../app/flags';
import {usePageTitle} from '../app/Shell';
import {EmptyState, ErrorState, Spinner} from '../components/States';
import {useI18n} from '../i18n/i18n';
import {clampIndex, stepForKey} from '../stories/stories';
import {StoryCard} from '../stories/StoryCard';

export default function StoriesScreen() {
  const {t} = useI18n();
  const flags = useConfigFlags();
  const query = useStories();
  const feed = useRef<HTMLOListElement>(null);
  const [current, setCurrent] = useState(0);
  usePageTitle(t('stories.title'));

  const stories = query.data?.pages.flatMap(p => p.stories) ?? [];
  const total = query.data?.pages[0]?.totalSize ?? stories.length;
  const {hasNextPage, isFetchingNextPage, fetchNextPage} = query;

  // Track which card is in view, and fetch the next page before the end.
  useEffect(() => {
    const root = feed.current;
    if (!root) return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const i = Number((entry.target as HTMLElement).dataset.storyIndex);
            if (Number.isFinite(i)) setCurrent(i);
          }
        }
      },
      {root, threshold: 0.6},
    );
    root
      .querySelectorAll('[data-story-index]')
      .forEach(el => observer.observe(el));
    return () => observer.disconnect();
  }, [stories.length]);
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && current >= stories.length - 2) {
      void fetchNextPage();
    }
  }, [current, stories.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const move = useCallback(
    (index: number) => {
      const target = clampIndex(index, stories.length);
      feed.current
        ?.querySelector<HTMLElement>(`[data-story-index="${target}"]`)
        ?.scrollIntoView({block: 'start'});
      setCurrent(target);
    },
    [stories.length],
  );

  function onKeyDown(event: KeyboardEvent<HTMLOListElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const step = stepForKey(event.key);
    if (!step) return;
    event.preventDefault();
    move(current + step);
  }

  if (flags.stories === false) {
    return (
      <div className="page-header">
        <h1>{t('stories.title')}</h1>
        <p className="lead">{t('stories.empty')}</p>
      </div>
    );
  }

  return (
    <div className="stories-page">
      <header className="page-header">
        <p className="strapline">{t('stories.honest')}</p>
        <h1>{t('stories.title')}</h1>
        <p className="lead">{t('stories.lead')}</p>
      </header>
      {query.isPending ? (
        <Spinner />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : stories.length === 0 ? (
        <EmptyState title={t('stories.empty')} />
      ) : (
        <>
          <ol
            ref={feed}
            className="stories-feed"
            aria-label={t('stories.feed')}
            // The feed is a scroll region: focusable so keys work without a pointer.
            tabIndex={0}
            onKeyDown={onKeyDown}
          >
            {stories.map((story, i) => (
              <StoryCard
                key={story.name}
                story={story}
                index={i}
                total={total}
              />
            ))}
            <li className="stories-end">
              {hasNextPage ? (
                <button
                  className="btn btn--tonal"
                  disabled={isFetchingNextPage}
                  onClick={() => void fetchNextPage()}
                >
                  {t('stories.more')}
                </button>
              ) : (
                <p>{t('stories.end')}</p>
              )}
            </li>
          </ol>
          <p className="stories-hint">{t('stories.keys')}</p>
        </>
      )}
    </div>
  );
}
