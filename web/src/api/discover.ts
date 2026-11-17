/** Data hooks for the games hub (Credit check, path challenge) and Stories. */
import {useInfiniteQuery, useQuery} from '@tanstack/react-query';

import {api, unwrap, type Schemas} from './client';

export type TriviaQuiz = Schemas['TriviaQuiz'];
export type TriviaQuestion = Schemas['TriviaQuestion'];
export type TriviaOption = Schemas['TriviaOption'];
export type CheckTriviaResponse = Schemas['CheckTriviaResponse'];
export type PathChallenge = Schemas['PathChallenge'];
export type Story = Schemas['Story'];

const MINUTE = 60_000;

export function useTrivia(date: string) {
  return useQuery({
    queryKey: ['trivia', date],
    queryFn: () =>
      unwrap(api.GET('/v1/trivia/{date}', {params: {path: {date}}})),
    staleTime: 5 * MINUTE,
  });
}

export function checkTrivia(date: string, question: string, option: string) {
  return unwrap(
    api.POST('/v1/trivia/{date}:check', {
      params: {path: {date}},
      body: {question, option},
    }),
  );
}

export function usePathChallenge(date: string) {
  return useQuery({
    queryKey: ['pathChallenge', date],
    queryFn: () =>
      unwrap(api.GET('/v1/pathChallenges/{date}', {params: {path: {date}}})),
    staleTime: 5 * MINUTE,
  });
}

const STORIES_PAGE = 6;

/** The stories feed, one page at a time. Pages are tied to the catalog version by the token. */
export function useStories() {
  return useInfiniteQuery({
    queryKey: ['stories'],
    initialPageParam: '',
    queryFn: ({pageParam}) =>
      unwrap(
        api.GET('/v1/stories', {
          params: {query: {pageSize: STORIES_PAGE, pageToken: pageParam}},
        }),
      ),
    getNextPageParam: last => last.nextPageToken || undefined,
    staleTime: 30 * MINUTE,
  });
}
