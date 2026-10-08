/** Compatibility for shared prototype URLs; v2 uses screen-specific routes. */
export function legacyDestination(search: string): string | null {
  const params = new URLSearchParams(search);
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const id = (key: string) => {
    const value = params.get(key);
    return value && uuid.test(value) ? value : null;
  };
  const play = params.get('play');
  const tab = params.get('tab');
  let destination: string | null = null;
  if (play) destination = `/play?date=${encodeURIComponent(play)}`;
  else if (tab === 'play') destination = '/play';
  else if (tab === 'connect' || (!tab && (id('from') || id('to')))) {
    const ends = new URLSearchParams();
    for (const key of ['from', 'to']) {
      const value = id(key);
      if (value) ends.set(key, value);
    }
    destination = `/six-degrees${ends.size ? `?${ends}` : ''}`;
  } else if (tab === 'explore' || (!tab && id('artist'))) {
    destination = `/explore${id('artist') ? `/${id('artist')}` : ''}`;
  }
  if (destination && params.has('locale')) {
    destination += `${destination.includes('?') ? '&' : '?'}locale=${encodeURIComponent(params.get('locale')!)}`;
  }
  return destination;
}
