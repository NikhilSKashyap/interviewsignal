// GET /api/auth/github/start
// Tells the candidate package that GitHub OAuth is not configured on this relay.
// The package interprets {"github_configured": false} as "continue with email-only identity".

import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({ github_configured: false })
}
