/**
 * The route error boundary (QA Q14). Without it, a render error or a failed
 * code-split chunk load shows a blank page.
 *
 * Chunk loads fail most often right after a deploy, when an open tab asks for
 * files the new release replaced; one automatic reload fixes that. A second
 * failure in the same session shows the message instead of looping.
 */
import {useEffect} from 'react';
import {useRouteError} from 'react-router';

import {ErrorState} from '../components/States';

const RELOADED_KEY = 'songnexus.reloadedAfterChunkError';

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module|Failed to fetch/i.test(
    message,
  );
}

function reloadedAlready(): boolean {
  try {
    return sessionStorage.getItem(RELOADED_KEY) === '1';
  } catch {
    return true;
  }
}

export function RouteError() {
  const error = useRouteError();
  const staleChunk = isChunkLoadError(error) && !reloadedAlready();

  useEffect(() => {
    if (!staleChunk) return;
    try {
      sessionStorage.setItem(RELOADED_KEY, '1');
    } catch {
      return;
    }
    window.location.reload();
  }, [staleChunk]);

  if (staleChunk) return null;
  return (
    <main id="main" className="main">
      <ErrorState error={error} onRetry={() => window.location.reload()} />
    </main>
  );
}
