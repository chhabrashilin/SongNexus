/** Data hooks for the games hub (Credit check, path challenge, leaderboards) and Stories. */
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

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

export function usePathChallenge(date: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['pathChallenge', date],
    queryFn: () =>
      unwrap(api.GET('/v1/pathChallenges/{date}', {params: {path: {date}}})),
    staleTime: 5 * MINUTE,
  });
}

export type Game = Schemas['Game'];
export type LeaderboardPeriod = Schemas['LeaderboardPeriod'];
export type GameScore = Schemas['GameScore'];
export type CampusLeaderboard = Schemas['CampusLeaderboard'];
export type FriendLeaderboard = Schemas['FriendLeaderboard'];

const me = {params: {path: {user: 'me'}}} as const;

/** The signed-in player's own scores of the last two weeks (to know what is already submitted). */
export function useGameScores(enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: ['me', 'gameScores'],
    queryFn: () => unwrap(api.GET('/v1/users/{user}/gameScores', me)),
    staleTime: MINUTE,
  });
}

/** Top campuses for a game and period. `date` is the player's local day. */
export function useCampusLeaderboard(
  game: Game,
  period: LeaderboardPeriod,
  date: string,
  enabled = true,
) {
  return useQuery({
    enabled,
    queryKey: ['leaderboards', 'campuses', game, period, date],
    queryFn: () =>
      unwrap(
        api.GET('/v1/leaderboards/campuses', {
          params: {query: {game, period, date}},
        }),
      ),
    staleTime: MINUTE,
  });
}

/** The player and their accepted friends who scored in the period. */
export function useFriendLeaderboard(
  game: Game,
  period: LeaderboardPeriod,
  date: string,
  enabled: boolean,
) {
  return useQuery({
    enabled,
    queryKey: ['me', 'friendLeaderboard', game, period, date],
    queryFn: () =>
      unwrap(
        api.GET('/v1/users/{user}/friendLeaderboard', {
          params: {path: {user: 'me'}, query: {game, period, date}},
        }),
      ),
    staleTime: MINUTE,
  });
}

export type ScoreSubmission =
  | {game: 'PUZZLE'; date: string; moves: string[]}
  | {
      game: 'TRIVIA';
      date: string;
      answers: {question: string; option: string}[];
    };

/** Opt-in: the server checks the play, computes the points and keeps one score per day. */
export function submitScore(play: ScoreSubmission): Promise<GameScore> {
  return play.game === 'PUZZLE'
    ? unwrap(
        api.POST('/v1/puzzles/{date}:submitScore', {
          params: {path: {date: play.date}},
          body: {moves: play.moves},
        }),
      )
    : unwrap(
        api.POST('/v1/trivia/{date}:submitScore', {
          params: {path: {date: play.date}},
          body: {answers: play.answers},
        }),
      );
}

export function useSubmitScore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: submitScore,
    onSettled: () => {
      void queryClient.invalidateQueries({queryKey: ['me', 'gameScores']});
      void queryClient.invalidateQueries({queryKey: ['leaderboards']});
      void queryClient.invalidateQueries({
        queryKey: ['me', 'friendLeaderboard'],
      });
    },
  });
}

const STORIES_PAGE = 6;

/** The stories feed, one page at a time. Pages are tied to the catalog version by the token. */
export function useStories(enabled = true) {
  return useInfiniteQuery({
    enabled,
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
