/** Snackbars: brief confirmations with an optional action (e.g. Undo), announced politely. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

interface Snack {
  id: number;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

type Show = (
  message: string,
  action?: {label: string; onAction: () => void},
) => void;

const SnackbarContext = createContext<Show>(() => undefined);
const VISIBLE_MS = 5000;

export function SnackbarProvider({children}: {children: ReactNode}) {
  const [snack, setSnack] = useState<Snack | null>(null);

  const show = useCallback<Show>((message, action) => {
    setSnack(
      action
        ? {
            id: Date.now(),
            message,
            actionLabel: action.label,
            onAction: action.onAction,
          }
        : {id: Date.now(), message},
    );
  }, []);

  useEffect(() => {
    if (!snack) return;
    const timer = window.setTimeout(() => setSnack(null), VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [snack]);

  const value = useMemo(() => show, [show]);
  return (
    <SnackbarContext.Provider value={value}>
      {children}
      <div aria-live="polite" aria-atomic="true">
        {snack && (
          <div className="snackbar" key={snack.id}>
            <span style={{flex: 1}}>{snack.message}</span>
            {snack.actionLabel && (
              <button
                type="button"
                className="btn btn--text"
                onClick={() => {
                  snack.onAction?.();
                  setSnack(null);
                }}
              >
                {snack.actionLabel}
              </button>
            )}
          </div>
        )}
      </div>
    </SnackbarContext.Provider>
  );
}

export function useSnackbar(): Show {
  return useContext(SnackbarContext);
}
