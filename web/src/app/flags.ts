/** Feature flags from /v1/config. Until loaded, everything defaults to on (kill switches turn off). */
import {useConfig} from '../api/queries';

export function useConfigFlags(): Record<string, boolean> {
  return useConfig().data?.flags ?? {};
}
