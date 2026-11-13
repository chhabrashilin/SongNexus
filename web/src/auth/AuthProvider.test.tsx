import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {act, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {AuthProvider, useAuth} from './AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {'Content-Type': 'application/json'},
  });
}

function error(status: number, code: string, reason: string): Response {
  return json(
    {error: {code: status, status: code, message: '', details: [{reason}]}},
    status,
  );
}

let auth: ReturnType<typeof useAuth> | null = null;
function Probe() {
  auth = useAuth();
  return <p>status: {auth.status}</p>;
}

describe('AuthProvider', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('stays signed in when the age dialog closes after confirming', async () => {
    let localCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request | string) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/v1/sessions/current'))
          return Promise.resolve(
            error(401, 'UNAUTHENTICATED', 'SIGN_IN_REQUIRED'),
          );
        if (url.includes('/v1/sessions:local'))
          return Promise.resolve(
            localCalls++ === 0
              ? error(400, 'FAILED_PRECONDITION', 'AGE_CONFIRMATION_REQUIRED')
              : json({user: 'users/u1', csrfToken: 'csrf'}),
          );
        return Promise.resolve(
          json({flags: {localSignIn: true}, limits: {}, graphVersion: null}),
        );
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    );
    await screen.findByText('status: signedOut');

    await act(() => auth!.signIn());
    await screen.findByText('status: needsAgeConfirmation');

    // Confirming closes the dialog, and the dialog's close handler cancels.
    await act(async () => {
      await auth!.confirmAge();
      auth!.cancelSignIn();
    });
    await waitFor(() =>
      expect(screen.getByText('status: signedIn')).toBeDefined(),
    );
  });

  it('cancelling a pending age confirmation signs out', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request | string) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/v1/sessions/current'))
          return Promise.resolve(
            error(401, 'UNAUTHENTICATED', 'SIGN_IN_REQUIRED'),
          );
        if (url.includes('/v1/sessions:local'))
          return Promise.resolve(
            error(400, 'FAILED_PRECONDITION', 'AGE_CONFIRMATION_REQUIRED'),
          );
        return Promise.resolve(
          json({flags: {localSignIn: true}, limits: {}, graphVersion: null}),
        );
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    );
    await screen.findByText('status: signedOut');
    await act(() => auth!.signIn());
    await screen.findByText('status: needsAgeConfirmation');
    act(() => auth!.cancelSignIn());
    await screen.findByText('status: signedOut');
  });
});
