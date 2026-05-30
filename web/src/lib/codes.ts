const CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

function randomChars(n: number): string {
  return Array.from({ length: n }, () =>
    CHARS[Math.floor(Math.random() * CHARS.length)]
  ).join('')
}

// Generates INT-XXXX-XX
export function generateInterviewCode(): string {
  return `INT-${randomChars(4)}-${randomChars(2)}`
}
