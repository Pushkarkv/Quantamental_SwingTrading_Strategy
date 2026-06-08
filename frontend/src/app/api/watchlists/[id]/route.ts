import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function PUT(request: Request, props: { params: Promise<{ id: string }> }) {
  try {
    const params = await props.params;
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { name } = await request.json();
    if (!name) return NextResponse.json({ error: 'Name required' }, { status: 400 });

    const username = (session.user as any).username;
    const { id } = params;

    await queryBigQuery(
      `UPDATE \`adk-mini-project.user_data.watchlists\` SET name = @name WHERE id = @id AND username = @username`,
      { name, id, username }
    );

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist PUT Error:', error);
    return NextResponse.json({ error: 'Failed to rename watchlist' }, { status: 500 });
  }
}

export async function DELETE(request: Request, props: { params: Promise<{ id: string }> }) {
  try {
    const params = await props.params;
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const username = (session.user as any).username;
    const { id } = params;

    // Verify ownership
    const check = await queryBigQuery(
      `SELECT id FROM \`adk-mini-project.user_data.watchlists\` WHERE id = @id AND username = @username`,
      { id, username }
    );

    if (check.length > 0) {
      // Delete items
      await queryBigQuery(
        `DELETE FROM \`adk-mini-project.user_data.watchlist_items\` WHERE watchlist_id = @id`,
        { id }
      );
      // Delete watchlist
      await queryBigQuery(
        `DELETE FROM \`adk-mini-project.user_data.watchlists\` WHERE id = @id AND username = @username`,
        { id, username }
      );
    }

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist DELETE Error:', error);
    return NextResponse.json({ error: 'Failed to delete watchlist' }, { status: 500 });
  }
}
