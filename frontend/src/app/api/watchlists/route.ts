import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const username = (session.user as any).username;

    // Fetch all watchlists for the user
    const watchlists = await queryBigQuery(
      `SELECT id, name, FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', created_at) as created_at FROM \`adk-mini-project.user_data.watchlists\` WHERE username = @username ORDER BY created_at ASC`,
      { username }
    );

    return NextResponse.json({ watchlists });

  } catch (error) {
    console.error('Watchlists GET Error:', error);
    return NextResponse.json({ error: 'Failed to fetch watchlists' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { name } = await request.json();
    if (!name) return NextResponse.json({ error: 'Name required' }, { status: 400 });

    const username = (session.user as any).username;
    // Generate simple ID (in production use a real UUID library, but since Node edge doesn't have crypto.randomUUID consistently, we'll make a pseudo-uuid)
    const id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).substring(2, 15);

    await queryBigQuery(
      `INSERT INTO \`adk-mini-project.user_data.watchlists\` (id, username, name, created_at) VALUES (@id, @username, @name, CURRENT_TIMESTAMP())`,
      { id, username, name }
    );

    return NextResponse.json({ success: true, id, name });

  } catch (error) {
    console.error('Watchlists POST Error:', error);
    return NextResponse.json({ error: 'Failed to create watchlist' }, { status: 500 });
  }
}
