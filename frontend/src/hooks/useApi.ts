import { useEffect, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: Error | null;
}

/**
 * Fetch whenever `key` changes, cancelling the previous request so a slow
 * response can never overwrite a newer one. Pass `key = null` to skip.
 * Loading is derived (the settled key differs from the requested key), so the
 * effect only sets state from asynchronous callbacks.
 */
export function useApi<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): ApiState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => setSettled({ key, data, error: null }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setSettled({ key, data: null, error: error instanceof Error ? error : new Error(String(error)) });
      },
    );
    return () => controller.abort();
    // `load` is intentionally excluded: callers pass inline closures keyed by `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (key === null) return { data: null, error: null, loading: false };
  if (settled?.key !== key) return { data: null, error: null, loading: true };
  return { data: settled.data, error: settled.error, loading: false };
}
