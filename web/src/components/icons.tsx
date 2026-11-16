// Icons (Yuo Brand Identity, section 9): simple filled shapes with rounded geometry for things (home, book, leaf,
// lock, gear...), and plain strokes for direction and action glyphs (arrows, chevrons, plus, close). 24-unit
// grid, the current text colour, always decorative (aria-hidden): the text next to an icon carries the meaning.
import type { ReactNode } from "react";

type IconProps = { size?: number | string; className?: string };

function Svg({ size = "1.25em", className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** A filled icon: one silhouette, holes cut with the even-odd rule. */
function Solid({ size = "1.25em", className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      fillRule="evenodd"
      clipRule="evenodd"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const solid = (d: string) => (p: IconProps) => (
  <Solid {...p}>
    <path d={d} />
  </Solid>
);

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" strokeWidth="2.6" />
  </Svg>
);

export const LockIcon = solid(
  "M7 10V8a5 5 0 0 1 10 0v2h.5a2.5 2.5 0 0 1 2.5 2.5v6a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5v-6A2.5 2.5 0 0 1 6.5 10zM9.5 10h5V8a2.5 2.5 0 0 0-5 0zM12 13.75a1.75 1.75 0 1 0 0 3.5 1.75 1.75 0 0 0 0-3.5z",
);

export const LeafIcon = solid(
  "M4.6 20.4a1 1 0 0 1-.3-.9C4.2 10.6 9.8 4.6 19.5 4.3a.9.9 0 0 1 .9.9C20.1 14.2 14.7 19.6 6.6 19.9l-.9.8a.8.8 0 0 1-1.1-.3zM8 17.3l7.3-7.3-1.1-1.1-7.3 7.3z",
);

export const SproutIcon = solid(
  "M10.9 21a1 1 0 0 0 2.2 0v-7.9c3.7-.6 6-3.2 6.2-7a.9.9 0 0 0-.9-.9c-3.6.1-6 1.9-6.9 5.1C10.6 7.8 8.4 6.4 5.4 6.3a.9.9 0 0 0-.9.9c.2 3.9 2.5 6.4 6.4 6.9z",
);

export const CoinsIcon = solid(
  "M12 3c-4 0-7 1.3-7 3.25S8 9.5 12 9.5s7-1.3 7-3.25S16 3 12 3zM5 9.600v2.650c0 1.950 3 3.25 7 3.25s7-1.3 7-3.25V9.600c-1.5 1.2-4 1.9-7 1.900s-5.5-.7-7-1.900zM5 15.600v2.150C5 19.7 8 21 12 21s7-1.3 7-3.25V15.600c-1.5 1.2-4 1.9-7 1.900s-5.5-.7-7-1.900z",
);

export const KeyIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l8-8M16 7l2.5 2.5M14 9l2 2" />
  </Svg>
);

export const ComputerIcon = solid(
  "M5.5 4h13A2.5 2.5 0 0 1 21 6.5v7a2.5 2.5 0 0 1-2.5 2.5H13v2h2.5a1 1 0 0 1 0 2h-7a1 1 0 0 1 0-2H11v-2H5.5A2.5 2.5 0 0 1 3 13.5v-7A2.5 2.5 0 0 1 5.5 4z",
);

export const CloudIcon = solid(
  "M7 19a4.5 4.5 0 0 1-1-8.900A6 6 0 0 1 17.5 9a5 5 0 0 1 .5 10z",
);

export const SparkleIcon = solid(
  "M10 3c.7 4.2 2.3 5.8 6.5 7-4.2 1.2-5.8 2.8-6.5 7-.7-4.2-2.3-5.8-6.5-7 4.2-1.2 5.8-2.8 6.5-7zM18 13.5c.3 2.1 1.1 2.9 3.2 3.5-2.1.6-2.9 1.4-3.2 3.5-.3-2.1-1.1-2.9-3.2-3.5 2.1-.6 2.9-1.4 3.2-3.5z",
);

export const ArrowRightIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);

export const ArrowLeftIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Svg>
);

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const BookIcon = solid(
  "M3 6.200a1 1 0 0 1 .7-1c2.6-.700 5.1-.300 7.5 1.200v13.100c-2.4-1.4-4.7-1.8-7-1.300A1 1 0 0 1 3 17.200zM21 6.200a1 1 0 0 0-.7-1c-2.6-.700-5.1-.300-7.5 1.200v13.100c2.4-1.4 4.7-1.8 7-1.300a1 1 0 0 0 1.2-1z",
);

export const AlertIcon = solid(
  "M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM11 7a1 1 0 0 1 2 0v5.5a1 1 0 0 1-2 0zM12 15.25a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z",
);

export const QuestionIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4M12 16.6v.2" />
  </Svg>
);

export const UploadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 15V4.5M7.5 9L12 4.5 16.5 9M5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5V15" />
  </Svg>
);

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Svg>
);

export const ClockIcon = solid(
  "M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM11 7a1 1 0 0 1 2 0v4.5l2.8 1.700a1 1 0 0 1-1 1.700L11 12.600z",
);

export const GearIcon = (p: IconProps) => (
  <Solid {...p}>
    {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
      <rect key={a} x="10.2" y="2.2" width="3.6" height="5" rx="1.2" transform={`rotate(${a} 12 12)`} />
    ))}
    <path d="M12 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM12 9.25a2.75 2.75 0 1 1 0 5.5 2.75 2.75 0 0 1 0-5.5z" />
  </Solid>
);

export const MoreIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="5.5" cy="12" r="1.2" />
    <circle cx="12" cy="12" r="1.2" />
    <circle cx="18.5" cy="12" r="1.2" />
  </Svg>
);

export const ChatIcon = solid(
  "M5.5 4h13A2.5 2.5 0 0 1 21 6.5v8a2.5 2.5 0 0 1-2.5 2.5H11.300l-4.2 3.300A.7.7 0 0 1 6 19.700V17h-.5A2.5 2.5 0 0 1 3 14.5v-8A2.5 2.5 0 0 1 5.5 4zM7.5 8.75v1.5h9v-1.5zM7.5 12v1.5h6V12z",
);

export const ChevronRightIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.5 6l6 6-6 6" />
  </Svg>
);

export const ChevronDownIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 9.5l6 6 6-6" />
  </Svg>
);

export const PencilIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15.5 5l3.5 3.5L9 18.5l-4.5 1 1-4.5z" />
    <path d="M13.5 7l3.5 3.5" />
  </Svg>
);

export const FlameIcon = solid(
  "M12.8 2.700c.8 3.4 5.2 5.7 5.2 10.800a6 6 0 0 1-12 0c0-2.2.9-3.9 2.1-5.2.4 1.5 1.1 2.5 2.1 3-.2-3.2.6-6.1 2.6-8.600z",
);

export const TrophyIcon = solid(
  "M7 4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v1h2.5a1 1 0 0 1 1 1v1.5a4.5 4.5 0 0 1-4 4.5A5 5 0 0 1 13 15.400V18h2.5a1 1 0 0 1 0 2h-7a1 1 0 0 1 0-2H11v-2.600A5 5 0 0 1 7.5 12a4.5 4.5 0 0 1-4-4.5V6a1 1 0 0 1 1-1H7zM7 7H5.5v.5A2.5 2.5 0 0 0 7 9.800zM17 7v2.800A2.5 2.5 0 0 0 18.5 7.5V7z",
);

export const BoltIcon = solid(
  "M13.9 2.600a.7.7 0 0 1 .5.800L13.3 9.5h4.900a.7.7 0 0 1 .6 1.100l-8 10.5a.7.7 0 0 1-1.2-.6l1.1-6.5H5.800a.7.7 0 0 1-.6-1.100l8-10.100a.7.7 0 0 1 .7-.2z",
);

export const SendIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 12L20 4.5 16.5 20l-4-5.5z" />
    <path d="M12.5 14.5L20 4.5" />
  </Svg>
);

export const RepeatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 11a7 7 0 0 1 12.2-4.7L19 8M19 4v4h-4" />
    <path d="M19 13a7 7 0 0 1-12.2 4.7L5 16M5 20v-4h4" />
  </Svg>
);

export const SignOutIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.5 4.5H6.5a1.5 1.5 0 0 0-1.5 1.5v12a1.5 1.5 0 0 0 1.5 1.5h7" />
    <path d="M10 12h10M16.5 8.5L20 12l-3.5 3.5" />
  </Svg>
);

export const DownloadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4.5V15M7.5 10.5L12 15l4.5-4.5M5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5V15" />
  </Svg>
);

export const NoteIcon = solid(
  "M6.5 3.5h7.700a1 1 0 0 1 .7.300l4.3 4.300a1 1 0 0 1 .3.700V18.5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2zM8 11.25v1.5h8v-1.5zM8 14.75v1.5h5.5v-1.5z",
);

export const HomeIcon = solid(
  "M11.3 3.300a1.1 1.1 0 0 1 1.4 0l8 6.800a1 1 0 0 1-1.2 1.600l-.5-.4V19.5A1.5 1.5 0 0 1 17.5 21H14.5v-5.5h-5V21H6.5A1.5 1.5 0 0 1 5 19.5v-8.200l-.5.400a1 1 0 0 1-1.2-1.600z",
);

export const BookmarkIcon = solid(
  "M7.5 3.5h9A2 2 0 0 1 18.5 5.5v14a.8.8 0 0 1-1.2.7L12 17l-5.3 3.200a.8.8 0 0 1-1.2-.7v-14A2 2 0 0 1 7.5 3.5z",
);

export const ProfileIcon = solid(
  "M12 3.5a4.25 4.25 0 1 0 0 8.5 4.25 4.25 0 0 0 0-8.5zM4 19.5c0-3.6 3.6-5.7 8-5.700s8 2.1 8 5.700a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z",
);

export const BudIcon = solid(
  "M11.3 3.300a1 1 0 0 1 1.4 0C15.5 6.3 17 9 17 11.600a5 5 0 0 1-4 4.900V20a1 1 0 0 1-2 0v-3.5a5 5 0 0 1-4-4.900C7 9 8.5 6.3 11.3 3.300z",
);

export const PlayIcon = solid(
  "M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM10 8.600a.6.6 0 0 1 .9-.5l5.3 3.400a.6.6 0 0 1 0 1l-5.3 3.400a.6.6 0 0 1-.9-.5z",
);

export const PracticeIcon = solid(
  "M6 3.5h12A2.5 2.5 0 0 1 20.5 6v12a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 18V6A2.5 2.5 0 0 1 6 3.5zM7 7.25h2v2H7zM11 7.5h6V9h-6zM7 11h2v2H7zM11 11.25h6v1.5h-6zM7 14.75h2v2H7zM11 15h6v1.5h-6z",
);

export const PathIcon = (p: IconProps) => (
  <Solid {...p}>
    <path d="M12 6v6.5M12 12.5l-5.5 5M12 12.5l5.5 3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="5.5" r="3" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </Solid>
);

export const ProgressIcon = (p: IconProps) => (
  <Solid {...p}>
    <rect x="3.5" y="13" width="4.5" height="8" rx="1.5" />
    <rect x="9.75" y="8.5" width="4.5" height="12.5" rx="1.5" />
    <rect x="16" y="3.5" width="4.5" height="17.5" rx="1.5" />
  </Solid>
);

export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10.5" cy="10.5" r="6" strokeWidth="2.6" />
    <path d="M15.2 15.2l4.8 4.8" strokeWidth="2.6" />
  </Svg>
);

export const CodeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5" strokeWidth="2.6" />
  </Svg>
);
