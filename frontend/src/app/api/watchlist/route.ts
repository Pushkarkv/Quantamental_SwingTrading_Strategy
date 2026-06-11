import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';
import { auth } from '@/lib/auth';

// Ensure table exists on first run (in a real app, do this in migrations)
async function initWatchlistTable() {
  try {
    await queryBigQuery(`
      CREATE SCHEMA IF NOT EXISTS \`adk-mini-project.user_data\`
    `);
  } catch (e) { /* ignore if exists */ }
  
  try {
    await queryBigQuery(`
      CREATE TABLE IF NOT EXISTS \`adk-mini-project.user_data.watchlist\` (
        username STRING,
        nse_symbol STRING,
        added_at TIMESTAMP
      )
    `);
  } catch (e) { /* ignore if exists */ }
}

export async function GET(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Fire-and-forget initialization
    initWatchlistTable().catch(console.error);

    const username = (session.user as any).username;

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
        w.added_at
      FROM \`adk-mini-project.user_data.watchlist\` w
      LEFT JOIN RankedPredictions p ON w.nse_symbol = p.nse_symbol AND p.rn = 1
      WHERE w.username = @username
      ORDER BY w.added_at DESC
    `;

    const results = await queryBigQuery(query, { username });
    return NextResponse.json({ results });

  } catch (error) {
    console.error('Watchlist GET Error:', error);
    return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { symbol } = await request.json();
    if (!symbol) return NextResponse.json({ error: 'Symbol required' }, { status: 400 });

    const username = (session.user as any).username;

    // Check if already exists
    const check = await queryBigQuery(
      `SELECT nse_symbol FROM \`adk-mini-project.user_data.watchlist\` WHERE username = @username AND nse_symbol = @symbol`,
      { username, symbol }
    );

    if (check.length === 0) {
      await queryBigQuery(
        `INSERT INTO \`adk-mini-project.user_data.watchlist\` (username, nse_symbol, added_at) VALUES (@username, @symbol, CURRENT_TIMESTAMP())`,
        { username, symbol }
      );
    }

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist POST Error:', error);
    return NextResponse.json({ error: 'Failed to add to watchlist' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const session = await auth();
    if (!session || !session.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { symbol } = await request.json();
    if (!symbol) return NextResponse.json({ error: 'Symbol required' }, { status: 400 });

    const username = (session.user as any).username;

    await queryBigQuery(
      `DELETE FROM \`adk-mini-project.user_data.watchlist\` WHERE username = @username AND nse_symbol = @symbol`,
      { username, symbol }
    );

    return NextResponse.json({ success: true });

  } catch (error) {
    console.error('Watchlist DELETE Error:', error);
    return NextResponse.json({ error: 'Failed to remove from watchlist' }, { status: 500 });
  }
}
