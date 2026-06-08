import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

// Revalidate this route every 1 hour (3600 seconds) since predictions update daily
export const revalidate = 3600;

export async function GET() {
  try {
    const baseQuery = `
      WITH RankedPredictions AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY nse_symbol ORDER BY prediction_date DESC) as rn
        FROM \`adk-mini-project.predictions.daily_inference_results\`
      ),
      LatestPrices AS (
        SELECT symbol, close as latest_close_price, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
        FROM \`adk-mini-project.technicals.daily_stock_price\`
      )
      SELECT 
        p.nse_symbol,
        p.stock_name,
        p.sector_l1,
        p.sector_l2,
        p.sector_l3,
        p.price_on_t0_inr as t0_price,
        lp.latest_close_price as current_price,
        p.predicted_upside_pct,
        p.predicted_downside_pct,
        p.predicted_avg_pct,
        p.risk_probability,
        p.risk_flag_balanced_0_50,
        p.risk_flag_lenient_0_55,
        p.risk_flag_aggressive_0_45
      FROM RankedPredictions p
      LEFT JOIN LatestPrices lp ON p.nse_symbol = lp.symbol AND lp.rn = 1
      WHERE p.rn = 1
    `;

    const results = await queryBigQuery(baseQuery);
    return NextResponse.json({ results });
  } catch (error) {
    console.error('Screener API Error:', error);
    return NextResponse.json({ error: 'Failed to fetch screener data' }, { status: 500 });
  }
}
