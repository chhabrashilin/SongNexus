/** Application root: providers and routes. Screens beyond the first view are code-split. */
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {useEffect, useState, type ComponentType, type ReactNode} from 'react';
import {
  createBrowserRouter,
  redirect,
  RouterProvider,
  type RouteObject,
} from 'react-router';

import {shouldRetry} from '../api/queries';
import {AuthProvider} from '../auth/AuthProvider';
import {SnackbarProvider} from '../components/Snackbar';
import {I18nProvider, useI18n, type Locale} from '../i18n/i18n';
import {HomeScreen} from '../screens/HomeScreen';
import {NotFoundScreen} from '../screens/NotFoundScreen';

import {RouteError} from './RouteError';
import {Shell} from './Shell';
import {ThemeSync} from './theme';
import {legacyDestination} from './legacyLinks';

/** Pages removed in the YouTube Music redesign, and where their links go now. */
const RETIRED: Record<string, string> = {
  discover: '/explore',
  guide: '/explore',
  'your-music': '/library',
  reels: '/stories',
};

/**
 * A screen whose code loads when it is first visited. The router loads it
 * before it switches pages, so the current page stays on screen until the next
 * one can draw: no spinner flash and no blank main area between pages.
 */
function screen(load: () => Promise<{default: ComponentType}>) {
  return async () => ({Component: (await load()).default});
}

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        element: <HomeScreen />,
        loader: ({request}) => {
          const destination = legacyDestination(new URL(request.url).search);
          return destination ? redirect(destination) : null;
        },
      },
      {
        path: 'artist/:id',
        lazy: screen(() => import('../screens/ArtistScreen')),
      },
      {
        path: 'explore',
        lazy: screen(() => import('../screens/ExploreHubScreen')),
      },
      {
        path: 'explore/:id',
        lazy: screen(() => import('../screens/ExploreScreen')),
      },
      {
        path: 'six-degrees',
        lazy: screen(() => import('../screens/SixDegreesScreen')),
      },
      {
        path: 'compare',
        lazy: screen(() => import('../screens/CompareScreen')),
      },
      {
        path: 'song/:id',
        lazy: screen(() => import('../screens/SongScreen')),
      },
      {
        path: 'artist/:id/collaborations',
        lazy: screen(() => import('../screens/CollaborationsScreen')),
      },
      {
        path: 'compare/songs',
        lazy: screen(() => import('../screens/SongCompareScreen')),
      },
      {
        path: 'label/:id',
        lazy: screen(() => import('../screens/LabelScreen')),
      },
      {
        path: 'genre/:id',
        lazy: screen(() => import('../screens/GenreScreen')),
      },
      {
        path: 'games',
        lazy: screen(() => import('../screens/GamesScreen')),
      },
      {
        path: 'stories',
        lazy: screen(() => import('../screens/StoriesScreen')),
      },
      {
        path: 'around-you',
        lazy: screen(() => import('../screens/AroundYouScreen')),
      },
      {
        path: 'play',
        lazy: screen(() => import('../screens/PlayScreen')),
      },
      {
        path: 'library',
        lazy: screen(() => import('../screens/LibraryScreen')),
      },
      {
        path: 'friends',
        lazy: screen(() => import('../screens/FriendsScreen')),
      },
      {
        path: 'friends/join/:code',
        lazy: screen(() => import('../screens/JoinFriendScreen')),
      },
      {
        path: 'you',
        lazy: screen(() => import('../screens/YouScreen')),
      },
      {
        path: 'about',
        lazy: screen(() => import('../screens/AboutScreen')),
      },
      {
        path: 'privacy',
        lazy: screen(() => import('../screens/PrivacyScreen')),
      },
      // Retired hub pages: old links land on the page that replaced them.
      ...Object.entries(RETIRED).map(([path, to]) => ({
        path,
        loader: () => redirect(to),
      })),
      {path: '*', element: <NotFoundScreen />},
    ],
  },
];

function DocumentLocale() {
  const {locale, dir} = useI18n();
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [locale, dir]);
  return null;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {retry: shouldRetry, refetchOnWindowFocus: false},
    },
  });
}

export function Providers({
  locale,
  client,
  children,
}: {
  locale: Locale;
  client: QueryClient;
  children: ReactNode;
}) {
  return (
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale}>
        <DocumentLocale />
        <AuthProvider>
          <ThemeSync />
          <SnackbarProvider>{children}</SnackbarProvider>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

export function App({locale}: {locale: Locale}) {
  const [client] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <Providers locale={locale} client={client}>
      <RouterProvider router={router} />
    </Providers>
  );
}
