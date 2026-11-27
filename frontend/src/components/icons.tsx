// Linear, angular SVG icons (miter joins, no rounded caps).
type P = { className?: string };
const base = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinejoin: "miter" as const,
  strokeLinecap: "square" as const,
};

export const IconMap = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" />
    <path d="M9 4v14M15 6v14" />
  </svg>
);
export const IconLots = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M4 7l8-4 8 4-8 4z" />
    <path d="M4 12l8 4 8-4M4 17l8 4 8-4" />
  </svg>
);
export const IconAlert = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M12 3l10 18H2z" />
    <path d="M12 10v5M12 17.5v1" />
  </svg>
);
export const IconFile = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M6 2h9l5 5v15H6z" />
    <path d="M15 2v5h5M9 12h8M9 16h8" />
  </svg>
);
export const IconChart = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M3 21h18M6 17v-6M11 17V7M16 17v-9M21 17V4" />
  </svg>
);
export const IconChat = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M3 4h18v13H9l-5 4v-4H3z" />
  </svg>
);
export const IconExit = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M10 4H4v16h6M14 8l4 4-4 4M18 12H9" />
  </svg>
);
