// Minimal stroke icons (24px grid, currentColor). Decorative unless given a label.

interface IconProps {
  size?: number;
  label?: string;
}

function Svg({ size = 16, label, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {children}
    </svg>
  );
}

export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Svg>
);
export const SwapIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 4v16M7 4 3 8M7 4l4 4M17 20V4m0 16-4-4m4 4 4-4" />
  </Svg>
);
export const SunIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
);
export const MoonIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
  </Svg>
);
export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5 12 5 5L20 7" />
  </Svg>
);
export const AlertIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3 2 21h20L12 3Z" />
    <path d="M12 10v4M12 17.5v.5" />
  </Svg>
);
export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);
export const FitIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </Svg>
);
export const SparkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />
  </Svg>
);

/** Brand mark: two linked nodes. */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill="var(--accent-soft)" />
      <path d="M10 20.5 21.5 11" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M10 20.5 22.5 21" stroke="var(--neutral-soft)" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="20.5" r="4" fill="var(--accent)" />
      <circle cx="21.5" cy="11" r="3.2" fill="var(--text)" />
      <circle cx="22.5" cy="21" r="2.2" fill="var(--neutral-strong)" />
    </svg>
  );
}
