import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {App} from './App';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {'Content-Type': 'application/json'},
  });
}

describe('App', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders the home screen for a signed-out visitor', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request | string) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/v1/sessions/current')) {
          return Promise.resolve(
            jsonResponse(
              {
                error: {
                  code: 401,
                  status: 'UNAUTHENTICATED',
                  message: '',
                  details: [{reason: 'SIGN_IN_REQUIRED'}],
                },
              },
              401,
            ),
          );
        }
        return Promise.resolve(
          jsonResponse({flags: {}, limits: {}, graphVersion: null}),
        );
      }),
    );
    render(<App locale="en-US" />);
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Discover who made the music you love',
      }),
    ).toBeDefined();
    expect(screen.getByRole('navigation', {name: 'Main'})).toBeDefined();
    expect(
      screen.getByRole('combobox', {name: 'Search artists and songs'}),
    ).toBeDefined();
  });
});
