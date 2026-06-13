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

    const presets = await queryBigQuery(
      `SELECT id, name, filters, FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', created_at) as created_at 
       FROM \`adk-mini-project.user_data.screener_presets\` 
       WHERE username = @username ORDER BY created_at ASC`,
      { username }
    );

    return NextResponse.json({ presets });

  } catch (error) {
    console.error('Presets GET Error:', error);
    return NextResponse.json({ error: 'Failed to fetch presets' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { name, filters } = await request.json();
    if (!name || !filters) return NextResponse.json({ error: 'Name and filters required' }, { status: 400 });

    const username = (session.user as any).username;
    const id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).substring(2, 15);

    await queryBigQuery(
      `INSERT INTO \`adk-mini-project.user_data.screener_presets\` (id, username, name, filters, created_at) 
       VALUES (@id, @username, @name, @filters, CURRENT_TIMESTAMP())`,
      { id, username, name, filters: JSON.stringify(filters) }
    );

    return NextResponse.json({ success: true, id, name, filters: JSON.stringify(filters) });

  } catch (error) {
    console.error('Presets POST Error:', error);
    return NextResponse.json({ error: 'Failed to create preset' }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id, name, filters } = await request.json();
    if (!id || !name || !filters) return NextResponse.json({ error: 'ID, name, and filters required' }, { status: 400 });

    const username = (session.user as any).username;

    await queryBigQuery(
      `UPDATE \`adk-mini-project.user_data.screener_presets\` 
       SET name = @name, filters = @filters 
       WHERE id = @id AND username = @username`,
      { id, username, name, filters: JSON.stringify(filters) }
    );

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Presets PUT Error:', error);
    return NextResponse.json({ error: 'Failed to update preset' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');
    
    if (!id) return NextResponse.json({ error: 'Preset ID required' }, { status: 400 });

    const username = (session.user as any).username;

    await queryBigQuery(
      `DELETE FROM \`adk-mini-project.user_data.screener_presets\` WHERE id = @id AND username = @username`,
      { id, username }
    );

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Presets DELETE Error:', error);
    return NextResponse.json({ error: 'Failed to delete preset' }, { status: 500 });
  }
}
