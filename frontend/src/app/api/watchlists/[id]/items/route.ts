import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function GET(request: Request, props: { params: Promise<{ id: string }> }) {
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
    if (check.length === 0) return NextResponse.json({ error: 'Not found' }, { status: 404 });

    const query = `
      WITH RankedPredictions AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY nse_symbol ORDER BY prediction_date DESC) as rn
        FROM \`adk-mini-project.predictions.daily_inference_results\`
      )
      SELECT 
        w.nse_symbol,
        p.stock_name,
        p.price_on_t0_inr as current_price,
        p.predicted_upside_pct,
        p.predicted_downside_pct,
        p.predicted_avg_pct,
        p.risk_probability,
        p.risk_flag_balanced_0_50,
        FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', w.added_at) as added_at
      FROM \`adk-mini-project.user_data.watchlist_items\` w
      LEFT JOIN RankedPredictions p ON w.nse_symbol = p.nse_symbol AND p.rn = 1
      WHERE w.watchlist_id = @id
      ORDER BY w.added_at DESC
    `;

    const results = await queryBigQuery(query, { id });
    return NextResponse.json({ results });

  } catch (error) {
    console.error('Watchlist Items GET Error:', error);
    return NextResponse.json({ error: 'Failed to fetch items' }, { status: 500 });
  }
}

export async function POST(request: Request, props: { params: Promise<{ id: string }> }) {
  try {
    const params = await props.params;
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { symbol } = await request.json();
    if (!symbol) return NextResponse.json({ error: 'Symbol required' }, { status: 400 });

    const username = (session.user as any).username;
    const { id } = params;

    // Verify ownership
    const checkUser = await queryBigQuery(
      `SELECT id FROM \`adk-mini-project.user_data.watchlists\` WHERE id = @id AND username = @username`,
      { id, username }
    );
    if (checkUser.length === 0) return NextResponse.json({ error: 'Not found' }, { status: 404 });

    // Check if already exists
    const checkItem = await queryBigQuery(
      `SELECT nse_symbol FROM \`adk-mini-project.user_data.watchlist_items\` WHERE watchlist_id = @id AND nse_symbol = @symbol`,
      { id, symbol }
    );

    if (checkItem.length === 0) {
      await queryBigQuery(
        `INSERT INTO \`adk-mini-project.user_data.watchlist_items\` (watchlist_id, nse_symbol, added_at) VALUES (@id, @symbol, CURRENT_TIMESTAMP())`,
        { id, symbol }
      );
    }

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist Items POST Error:', error);
    return NextResponse.json({ error: 'Failed to add item' }, { status: 500 });
  }
}

export async function DELETE(request: Request, props: { params: Promise<{ id: string }> }) {
  try {
    const params = await props.params;
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { symbol } = await request.json();
    if (!symbol) return NextResponse.json({ error: 'Symbol required' }, { status: 400 });

    const username = (session.user as any).username;
    const { id } = params;

    const checkUser = await queryBigQuery(
      `SELECT id FROM \`adk-mini-project.user_data.watchlists\` WHERE id = @id AND username = @username`,
      { id, username }
    );
    if (checkUser.length === 0) return NextResponse.json({ error: 'Not found' }, { status: 404 });

    await queryBigQuery(
      `DELETE FROM \`adk-mini-project.user_data.watchlist_items\` WHERE watchlist_id = @id AND nse_symbol = @symbol`,
      { id, symbol }
    );

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist Items DELETE Error:', error);
    return NextResponse.json({ error: 'Failed to remove item' }, { status: 500 });
  }
}
