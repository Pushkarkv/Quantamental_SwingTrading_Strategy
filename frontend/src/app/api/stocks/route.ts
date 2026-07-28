import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '50', 10);
    const riskProfile = searchParams.get('riskProfile') || 'balanced';

    // 1. Get latest predictions
    const latestPredictionsQuery = `
      WITH RankedPredictions AS (
        SELECT 
          *,
          ROW_NUMBER() OVER (PARTITION BY nse_symbol ORDER BY prediction_date DESC) as rn
        FROM \`adk-mini-project.predictions.daily_inference_results\`
      )
      SELECT 
        nse_symbol,
        stock_name,
        sector_l1,
        sector_l2,
        CAST(prediction_date as STRING) as prediction_date,
        price_on_t0_inr,
        predicted_upside_pct,
        predicted_downside_pct,
        predicted_avg_pct,
        risk_probability,
        risk_flag_balanced_0_50
      FROM RankedPredictions
      WHERE rn = 1
    `;

    const predictions = await queryBigQuery(latestPredictionsQuery);

    // 2. Get actual last pipeline run date from execution_log (always accurate)
    const lastRunQuery = `
      SELECT MAX(run_date) as last_run_date
      FROM \`adk-mini-project.pipeline.execution_log\`
      WHERE status = 'SUCCESS'
    `;
    const lastRunResult = await queryBigQuery(lastRunQuery);

    // 3. Calculate stats
    const total = predictions.length;
    let passing = 0;
    let totalUpside = 0;

    const filtered = predictions.filter((p: any) => {
      // Basic filter for "top picks": balanced risk == 0, avg upside > 0
      const isPassing = p.risk_flag_balanced_0_50 === 0 && p.predicted_avg_pct > 0.05;
      if (isPassing) {
        passing++;
        totalUpside += p.predicted_upside_pct;
      }
      return isPassing;
    });

    // Sort by predicted average return DESC
    filtered.sort((a: any, b: any) => b.predicted_avg_pct - a.predicted_avg_pct);

    const stats = {
      total,
      passing,
      avgUpside: passing > 0 ? totalUpside / passing : 0,
      lastRun: lastRunResult.length > 0 && lastRunResult[0].last_run_date
        ? new Date(lastRunResult[0].last_run_date as string).toLocaleDateString()
        : 'N/A'
    };

    return NextResponse.json({
      stats,
      stocks: filtered.slice(0, limit)
    });

  } catch (error) {
    console.error('API Error:', error);
    return NextResponse.json({ error: 'Failed to fetch stocks data' }, { status: 500 });
  }
}
