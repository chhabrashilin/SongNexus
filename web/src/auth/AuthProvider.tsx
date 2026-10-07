/**
 * Signed-in state for the whole app (ADR 0002).
 *
 * The session lives in an HttpOnly cookie the page can't read; on load we ask
 * the server who we are and receive the CSRF token for writes.
 */
import {useQueryClient} from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {api, ApiError, setCsrfToken, unwrap} from '../api/client';

export type AuthStatus =
  'loading' | 'signedOut' | 'signingIn' | 'needsAgeConfirmation' | 'signedIn';

export type SignInProblem = 'failed' | 'popupBlocked' | 'notConfigured' | null;

interface AuthState {
  status: AuthStatus;
  user: string | null;
  problem: SignInProblem;
  signIn: () => Promise<void>;
  confirmAge: () => Promise<void>;
  cancelSignIn: () => void;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
  deleteAccount: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Maps a sign-in failure to what the user is told (closing the popup is not an error). */
export function signInProblem(error: unknown): SignInProblem {
  const code = (error as {code?: string}).code ?? '';
  if ((error as Error).name === 'SignInNotConfiguredError')
    return 'notConfigured';
  if (code === 'auth/popup-blocked') return 'popupBlocked';
  if (
    code === 'auth/popup-closed-by-user' ||
    code === 'auth/cancelled-popup-request'
  )
    return null;
  return 'failed';
}

export function AuthProvider({children}: {children: ReactNode}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<string | null>(null);
  const [problem, setProblem] = useState<SignInProblem>(null);
  const [pendingToken, setPendingToken] = useState<string | null>(null);

  const becomeSignedIn = useCallback(
    (session: {user: string; csrfToken: string}) => {
      setCsrfToken(session.csrfToken);
      setUser(session.user);
      setStatus('signedIn');
      setProblem(null);
      // Catalog responses are personalized (blocks) once signed in.
      void queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const becomeSignedOut = useCallback(() => {
    setCsrfToken(null);
    setUser(null);
    setPendingToken(null);
    setStatus('signedOut');
    queryClient.removeQueries({queryKey: ['me']});
    void queryClient.invalidateQueries();
  }, [queryClient]);

  // QA Q15: when the session expires or is revoked on another device, the next
  // request fails with UNAUTHENTICATED; reflect that instead of looking signed in.
  useEffect(() => {
    if (status !== 'signedIn') return;
    const expired = (error: unknown) =>
      error instanceof ApiError && error.status === 'UNAUTHENTICATED';
    const unsubscribeQueries = queryClient.getQueryCache().subscribe(event => {
      if (event.type === 'updated' && expired(event.query.state.error))
        becomeSignedOut();
    });
    const unsubscribeMutations = queryClient
      .getMutationCache()
      .subscribe(event => {
        if (event.type === 'updated' && expired(event.mutation?.state.error))
          becomeSignedOut();
      });
    return () => {
      unsubscribeQueries();
      unsubscribeMutations();
    };
  }, [status, queryClient, becomeSignedOut]);

  useEffect(() => {
    let active = true;
    unwrap(api.GET('/v1/sessions/current'))
      .then(session => active && becomeSignedIn(session))
      .catch(() => active && becomeSignedOut());
    return () => {
      active = false;
    };
  }, [becomeSignedIn, becomeSignedOut]);

  const createSession = useCallback(
    async (idToken: string, ageConfirmed: boolean) => {
      try {
        becomeSignedIn(
          await unwrap(
            api.POST('/v1/sessions', {body: {idToken, ageConfirmed}}),
          ),
        );
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.reason === 'AGE_CONFIRMATION_REQUIRED'
        ) {
          setPendingToken(idToken);
          setStatus('needsAgeConfirmation');
          return;
        }
        setProblem('failed');
        setStatus('signedOut');
      }
    },
    [becomeSignedIn],
  );

  const signIn = useCallback(async () => {
    setProblem(null);
    setStatus('signingIn');
    try {
      const {getGoogleIdToken} = await import('./firebase');
      await createSession(await getGoogleIdToken(), false);
    } catch (error) {
      setProblem(signInProblem(error));
      setStatus('signedOut');
    }
  }, [createSession]);

  const confirmAge = useCallback(async () => {
    if (pendingToken) await createSession(pendingToken, true);
    setPendingToken(null);
  }, [createSession, pendingToken]);

  const cancelSignIn = useCallback(() => {
    setPendingToken(null);
    setStatus('signedOut');
  }, []);

  const signOut = useCallback(async () => {
    await unwrap(api.DELETE('/v1/sessions/current')).catch(() => undefined);
    becomeSignedOut();
  }, [becomeSignedOut]);

  const signOutEverywhere = useCallback(async () => {
    await unwrap(api.POST('/v1/sessions:revokeAll'));
    becomeSignedOut();
  }, [becomeSignedOut]);

  const deleteAccount = useCallback(async () => {
    await unwrap(
      api.DELETE('/v1/users/{user}', {params: {path: {user: 'me'}}}),
    );
    becomeSignedOut();
  }, [becomeSignedOut]);

  const value = useMemo<AuthState>(
    () => ({
      status,
      user,
      problem,
      signIn,
      confirmAge,
      cancelSignIn,
      signOut,
      signOutEverywhere,
      deleteAccount,
    }),
    [
      status,
      user,
      problem,
      signIn,
      confirmAge,
      cancelSignIn,
      signOut,
      signOutEverywhere,
      deleteAccount,
    ],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
