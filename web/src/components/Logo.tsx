/**
 * The SongNexus mark: a red disc in the YouTube Music family, with three linked
 * artists arranged as a play triangle. It is our own mark, not YouTube's.
 */
export function LogoMark({className}: {className?: string}) {
  return (
    <svg
      className={className}
      viewBox="0 0 28 28"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="14" cy="14" r="14" fill="#ff0000" />
      <circle
        cx="14"
        cy="14"
        r="9.4"
        fill="none"
        stroke="#fff"
        strokeOpacity="0.38"
        strokeWidth="1"
      />
      <path
        d="M11 8.9 11 19.1 19.6 14Z"
        fill="none"
        stroke="#fff"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx="11" cy="8.9" r="2.3" fill="#fff" />
      <circle cx="11" cy="19.1" r="2.3" fill="#fff" />
      <circle cx="19.6" cy="14" r="2.3" fill="#fff" />
    </svg>
  );
}
