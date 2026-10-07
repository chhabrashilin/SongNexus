/**
 * The en-US message catalog (ICU MessageFormat). Every user-visible string
 * lives here, including empty, error and limitation states (plan §8).
 *
 * Wording rules: "connection", never "edge"; "steps apart", never "hops";
 * "not in our data yet", never "not connected". Sentence case. Digits.
 */
export const messages = {
  // App shell
  'app.name': 'SongNexus',
  'app.tagline': 'The people behind the music, and how they connect.',
  'app.skipToContent': 'Skip to main content',
  'nav.home': 'Home',
  'nav.explore': 'Explore',
  'nav.sixDegrees': 'Six degrees',
  'nav.play': 'Play',
  'nav.library': 'Library',
  'nav.you': 'You',
  'nav.primary': 'Main',

  // Generic states
  'state.loading': 'Loading…',
  'state.error.title': 'Something went wrong',
  'state.error.body': 'Check your connection and try again.',
  'state.unavailable.title': 'Our catalog is warming up',
  'state.unavailable.body': 'This takes a few seconds. Try again shortly.',
  'state.rateLimited':
    'You’re going a bit fast. Try again in {seconds, plural, one {# second} other {# seconds}}.',
  'state.notFound.title': 'Page not found',
  'state.notFound.body': 'The link may be broken or the page may have moved.',
  'action.retry': 'Try again',
  'action.close': 'Close',
  'action.cancel': 'Cancel',
  'action.save': 'Save',
  'action.undo': 'Undo',
  'action.showMore': 'Show more',
  'action.goHome': 'Go home',
  'action.share': 'Share',
  'action.copyLink': 'Copy link',
  'action.linkCopied': 'Link copied',

  // Search
  'search.label': 'Search artists and songs',
  'search.placeholder': 'Search artists and songs',
  'search.noResults': 'No matches in our data yet for “{query}”',
  'search.results':
    '{count, plural, one {# result} other {# results}} available',
  'search.type.ARTIST': 'Artist',
  'search.type.RELEASE': 'Album',
  'search.type.RECORDING': 'Song',
  'search.blocked': 'Hidden by you',

  // Home
  'home.title': 'Discover who made the music you love',
  'home.lead': 'Every connection comes with the credits that prove it.',
  'home.try': 'Try',
  'home.playCard.title': 'Today’s puzzle',
  'home.playCard.body': 'Link two artists one collaboration at a time.',
  'home.playCard.action': 'Play',
  'home.sixDegrees.title': 'Six degrees',
  'home.sixDegrees.body': 'Pick any two artists and see how they connect.',
  'home.import.title': 'Map your playlist',
  'home.import.body': 'See the hidden links between the artists you listen to.',
  'home.recent': 'Recently viewed',

  // Artist page
  'artist.connections':
    '{count, plural, one {# connection} other {# connections}}',
  'artist.explore': 'Explore connections',
  'artist.findPath': 'Find a path',
  'artist.compare': 'Compare',
  'artist.block': 'Don’t show this artist',
  'artist.unblock': 'Show this artist again',
  'artist.blocked': 'You hid this artist. It won’t appear in lists or paths.',
  'artist.genres': 'Genres',
  'artist.genresUnknown': 'Genre not in our data yet',
  'artist.aka': 'Also known as',
  'artist.links': 'Links',
  'artist.sources': 'Sources',
  'artist.detail.stub':
    'We know this artist from credits on other artists’ records, so this page is incomplete.',
  'artist.type.Person': 'Person',
  'artist.type.Group': 'Group',
  'artist.type.Orchestra': 'Orchestra',
  'artist.type.Choir': 'Choir',
  'artist.type.Character': 'Character',
  'artist.type.other': 'Artist',
  'collab.title': 'Collaborations',
  'collab.basis': 'Based on releases in our data.',
  'collab.tab.FEATURE': 'Features',
  'collab.tab.PRODUCTION': 'Production',
  'collab.tab.BAND': 'Bands and projects',
  'collab.tab.CREDIT': 'Credits',
  'collab.empty':
    'No {type, select, FEATURE {features} PRODUCTION {production credits} BAND {bands or projects} other {credits}} in our data yet.',
  'collab.count': '{count, plural, one {# credit} other {# credits}}',
  'collab.years': '{first, number, ::group-off}–{last, number, ::group-off}',
  'collab.year': '{year, number, ::group-off}',

  // Connections and evidence
  'connection.showEvidence': 'Show credits with {name}',
  'connection.strength': 'Strength {strength, number, ::.#}',
  'connection.strengthHelp': 'How many credits link them, weighted by kind.',
  'connection.evidenceTitle': 'How {a} and {b} are connected',
  'connection.evidenceCount':
    '{count, plural, one {# credit} other {# credits}}',
  'connection.source': 'Source: {host}',
  'subject.recording': 'a song',
  'subject.release': 'an album',
  'subject.label': 'a label',
  'subject.relation': 'a credit',
  'evidence.performedTogether':
    '{from} and {to} are both credited on {subject}',
  'evidence.featured': '{featured} is featured on {main}’s {subject}',
  'evidence.produced': '{producer} produced {performer}’s {subject}',
  'evidence.coProduced': '{from} and {to} co-produced {subject}',
  'evidence.contributed':
    '{contributor} played {role} on {performer}’s {subject}',
  'evidence.sampled': '{performer}’s {subject} samples {sampled}',
  'evidence.engineered': '{engineer} engineered {performer}’s {subject}',
  'evidence.labelMates':
    '{from} and {to} released on {subject} within a few years',
  'evidence.relation.member': '{a} is a member of {b}',
  'evidence.relation.subgroup': '{b} is a subgroup of {a}',
  'evidence.relation.person': '{a} performs as {b}',
  'evidence.relation.collaborator': '{a} is part of {b}',
  'evidence.relation.supporting': '{a} played in {b}’s band',
  'evidence.relation.teacher': '{a} taught {b}',
  'evidence.relation.other': '{a} and {b} worked together',
  'role.vocal': 'vocals',
  'role.instrument': 'an instrument',
  'role.performer': 'as a performer',
  'role.programming': 'programming',
  'role.arranger': 'arrangement',
  'role.conductor': 'as conductor',
  'role.remixer': 'a remix',
  'role.other': 'a part',

  // Categories
  'category.FEATURES': 'Features',
  'category.PRODUCERS': 'Producers',
  'category.CONTRIBUTIONS': 'Contributions',
  'category.SAMPLES': 'Samples',
  'category.BANDS': 'Bands',
  'category.LABELS': 'Labels',
  'category.ENGINEERING': 'Engineering',
  'filter.categories': 'Show connections through',
  'filter.genres': 'Stay within genres',
  'filter.genres.search': 'Find a genre',
  'filter.genres.coverage':
    'Genre known for {percent, number, ::percent} of artists here',
  'filter.genres.includeUnknown': 'Include artists with unknown genre',
  'filter.genres.none': 'Any genre',
  'filter.genres.selected': '{count, plural, one {# genre} other {# genres}}',

  // Explore
  'explore.title': 'Explore',
  'explore.lead': 'Start from an artist and expand their connections.',
  'explore.view.web': 'Web',
  'explore.view.list': 'List',
  'explore.expand': 'Show connections of {name}',
  'explore.truncated': 'Showing {shown} of {total} connections',
  'explore.empty': 'No connections match these filters in our data yet.',
  'explore.canvasLabel':
    'Connection web of {name}. Use the list view for a text version.',
  'explore.fit': 'Fit to screen',
  'explore.reset': 'Start over',
  'explore.legend': 'Legend',

  // Six degrees
  'path.title': 'Six degrees',
  'path.lead': 'How are two artists connected?',
  'path.from': 'From',
  'path.to': 'To',
  'path.swap': 'Swap artists',
  'path.find': 'Connect',
  'path.mode.FEWEST_STEPS': 'Fewest steps',
  'path.mode.STRONGEST_LINKS': 'Strongest links',
  'path.steps':
    '{count, plural, =0 {Same artist} one {# step apart} other {# steps apart}}',
  'path.notConnected': 'Not connected in our data yet (within {max} steps).',
  'path.limitReached':
    'We stopped looking: this search got too large. Try other filters.',
  'path.alternatives': 'Other routes',
  'path.sameArtist': 'Pick two different artists.',
  'path.announce': 'Path found: {names}',
  'path.skipAnimation': 'Skip animation',

  // Compare
  'compare.title': 'Compare',
  'compare.sharedGenres': 'Shared genres',
  'compare.overlap': '{percent, number, ::percent} genre overlap',
  'compare.noGenreData': 'Genre data is missing for one of them.',
  'compare.mutual': 'Worked with both',
  'compare.noMutual': 'No one in our data has worked with both yet.',
  'compare.direct': 'They have worked together directly.',
  'compare.path': 'How they connect',

  // Song
  'song.credits': 'Credits',
  'song.appearsOn': 'Appears on',
  'song.noCredits': 'No credits for this song in our data yet.',
  'song.role.primary': 'Main artist',
  'song.role.featured': 'Featured',
  'song.role.producer': 'Producer',
  'song.role.vocal': 'Vocals',
  'song.role.instrument': 'Instruments',
  'song.role.performer': 'Performer',
  'song.role.programming': 'Programming',
  'song.role.arranger': 'Arrangement',
  'song.role.conductor': 'Conductor',
  'song.role.remixer': 'Remix',
  'song.role.sampled': 'Sampled',
  'song.role.engineer': 'Engineering',
  'song.length': 'Length {minutes}:{seconds}',

  // Account
  'auth.signIn': 'Sign in with Google',
  'auth.signOut': 'Sign out',
  'auth.signOutEverywhere': 'Sign out on all devices',
  'auth.signingIn': 'Signing in…',
  'auth.failed': 'Sign-in didn’t work. Try again.',
  'auth.popupBlocked':
    'Your browser blocked the sign-in window. Allow pop-ups and try again.',
  'auth.notConfigured': 'Sign-in isn’t set up in this environment.',
  'auth.age.title': 'Create your account',
  'auth.age.body': 'SongNexus is for people aged 13 and older.',
  'auth.age.confirm': 'I’m 13 or older',
  'auth.age.continue': 'Create account',
  'you.title': 'You',
  'you.signedOut':
    'Sign in to keep your hidden artists, settings and Top 5 on every device.',
  'you.top5': 'Your Top 5',
  'you.top5.empty': 'Pick up to 5 artists. Only you can see this.',
  'you.top5.add': 'Add an artist',
  'you.top5.remove': 'Remove {name} from your Top 5',
  'you.top5.full': 'Your Top 5 is full. Remove one to add another.',
  'you.blocked': 'Hidden artists',
  'you.blocked.empty': 'You haven’t hidden any artists.',
  'you.settings': 'Settings',
  'you.theme': 'Theme',
  'you.theme.SYSTEM': 'System',
  'you.theme.LIGHT': 'Light',
  'you.theme.DARK': 'Dark',
  'you.data': 'Your data',
  'you.export': 'Download my data',
  'you.delete': 'Delete account',
  'you.delete.title': 'Delete your account?',
  'you.delete.body':
    'Your settings, hidden artists and Top 5 are deleted now. Everything is gone from our systems within 30 days. This can’t be undone.',
  'you.delete.confirm': 'Delete',
  'you.deleted': 'Your account was deleted.',
  'you.saved': 'Saved',
  'you.conflict':
    'This changed on another device. We loaded the latest version.',
  'block.done': '{name} hidden',
  'block.undone': '{name} shown again',

  // Pages
  'about.title': 'About our data',
  'privacy.title': 'Privacy',
  'footer.about': 'About our data',
  'footer.privacy': 'Privacy',
} as const;

export type MessageId = keyof typeof messages;
