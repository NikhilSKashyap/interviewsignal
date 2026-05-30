export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size * 1.25}
      viewBox="0 0 32 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="InterviewSignal"
    >
      {/* Signal arcs radiating from dot — largest to smallest (back to front) */}
      <path
        d="M16 11 m-10 0 a10 10 0 0 1 20 0"
        stroke="#34d399"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.25"
      />
      <path
        d="M16 11 m-6.5 0 a6.5 6.5 0 0 1 13 0"
        stroke="#34d399"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.55"
      />
      <path
        d="M16 11 m-3.5 0 a3.5 3.5 0 0 1 7 0"
        stroke="#34d399"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="1"
      />
      {/* Dot of the i */}
      <circle cx="16" cy="11" r="3" fill="white" />
      {/* Body of the i */}
      <rect x="13" y="19" width="6" height="17" rx="3" fill="white" />
    </svg>
  )
}
