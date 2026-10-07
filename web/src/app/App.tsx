/** Application root: providers and routes. Screens beyond the first view are code-split. */
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {lazy, Suspense, useEffect, useState, type ReactNode} from 'react';
import {
  createBrowserRouter,
  RouterProvider,
  type RouteObject,
} from 'react-router';

import {shouldRetry} from '../api/queries';
import {AuthProvider} from '../auth/AuthProvider';
import {SnackbarProvider} from '../components/Snackbar';
import {Spinner} from '../components/States';
import {I18nProvider, useI18n, type Locale} from '../i18n/i18n';
import {HomeScreen} from '../screens/HomeScreen';
import {NotFoundScreen} from '../screens/NotFoundScreen';

import {RouteError} from './RouteError';
import {Shell} from './Shell';
import {ThemeSync} from './theme';

const ArtistScreen = lazy(() => import('../screens/ArtistScreen'));
const ExploreScreen = lazy(() => import('../screens/ExploreScreen'));
const SixDegreesScreen = lazy(() => import('../screens/SixDegreesScreen'));
const CompareScreen = lazy(() => import('../screens/CompareScreen'));
const SongScreen = lazy(() => import('../screens/SongScreen'));
const YouScreen = lazy(() => import('../screens/YouScreen'));
const AboutScreen = lazy(() => import('../screens/AboutScreen'));
const PrivacyScreen = lazy(() => import('../screens/PrivacyScreen'));

function Lazy({children}: {children: ReactNode}) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      {index: true, element: <HomeScreen />},
      {
        path: 'artist/:id',
        element: (
          <Lazy>
            <ArtistScreen />
          </Lazy>
        ),
      },
      {
        path: 'explore',
        element: (
          <Lazy>
            <ExploreScreen />
          </Lazy>
        ),
      },
      {
        path: 'explore/:id',
        element: (
          <Lazy>
            <ExploreScreen />
          </Lazy>
        ),
      },
      {
        path: 'six-degrees',
        element: (
          <Lazy>
            <SixDegreesScreen />
          </Lazy>
        ),
      },
      {
        path: 'compare',
        element: (
          <Lazy>
            <CompareScreen />
          </Lazy>
        ),
      },
      {
        path: 'song/:id',
        element: (
          <Lazy>
            <SongScreen />
          </Lazy>
        ),
      },
      {
        path: 'you',
        element: (
          <Lazy>
            <YouScreen />
          </Lazy>
        ),
      },
      {
        path: 'about',
        element: (
          <Lazy>
            <AboutScreen />
          </Lazy>
        ),
      },
      {
        path: 'privacy',
        element: (
          <Lazy>
            <PrivacyScreen />
          </Lazy>
        ),
      },
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
