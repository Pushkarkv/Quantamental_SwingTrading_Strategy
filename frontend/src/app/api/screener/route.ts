import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

export async function POST(request: Request) {
  try {
    const filters = await request.json();
    
    let baseQuery = `
      WITH RankedPredictions AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY nse_symbol ORDER BY prediction_date DESC) as rn
        FROM \`adk-mini-project.predictions.daily_inference_results\`
      )
      SELECT 
        p.nse_symbol,
        p.stock_name,
        c.sector_classification,
        p.price_on_t0_inr as current_price,
        p.predicted_upside_pct,
        p.predicted_downside_pct,
        p.predicted_avg_pct,
        p.risk_probability,
        p.risk_flag_balanced_0_50,
        SAFE_CAST(k.Stock_P_E AS FLOAT64) as pe_ratio,
        k.Market_Cap as market_cap_str
      FROM RankedPredictions p
      LEFT JOIN \`adk-mini-project.fundamentals.company_info\` c ON p.nse_symbol = c.nse_symbol
      LEFT JOIN \`adk-mini-project.fundamentals.key_ratios\` k ON p.nse_symbol = k.nse_symbol
      WHERE p.rn = 1
    `;

    const params: Record<string, any> = {};

    // Apply Filters
    if (filters.minUpside) {
      baseQuery += ` AND p.predicted_upside_pct >= @minUpside`;
      params.minUpside = parseFloat(filters.minUpside) / 100;
    }
    
    if (filters.minAvgReturn) {
      baseQuery += ` AND p.predicted_avg_pct >= @minAvgReturn`;
      params.minAvgReturn = parseFloat(filters.minAvgReturn) / 100;
    }

    if (filters.maxRiskProb) {
      baseQuery += ` AND p.risk_probability <= @maxRiskProb`;
      params.maxRiskProb = parseFloat(filters.maxRiskProb) / 100;
    }

    if (filters.riskProfile && filters.riskProfile !== 'all') {
      if (filters.riskProfile === 'balanced') {
        baseQuery += ` AND p.risk_flag_balanced_0_50 = 0`;
      } else if (filters.riskProfile === 'aggressive') {
        baseQuery += ` AND p.risk_flag_aggressive_0_45 = 0`;
      } else if (filters.riskProfile === 'lenient') {
        baseQuery += ` AND p.risk_flag_lenient_0_55 = 0`;
      }
    }

    if (filters.sector && filters.sector !== 'all') {
      baseQuery += ` AND c.sector_classification LIKE @sector`;
      params.sector = `%${filters.sector}%`;
    }

    if (filters.maxPe) {
      baseQuery += ` AND SAFE_CAST(k.Stock_P_E AS FLOAT64) <= @maxPe`;
      params.maxPe = parseFloat(filters.maxPe);
    }

    // Order and Limit
    const sortCol = filters.sortBy || 'predicted_avg_pct';
    const sortDir = filters.sortDir === 'asc' ? 'ASC' : 'DESC';
    
    // Whitelist valid columns for sorting to prevent injection
    const validSortCols = ['predicted_upside_pct', 'predicted_avg_pct', 'risk_probability', 'current_price', 'pe_ratio'];
    const safeSortCol = validSortCols.includes(sortCol) ? sortCol : 'predicted_avg_pct';

    baseQuery += ` ORDER BY ${safeSortCol} ${sortDir} LIMIT 100`;

    const results = await queryBigQuery(baseQuery, params);

    return NextResponse.json({ results });

  } catch (error) {
    console.error('Screener API Error:', error);
    return NextResponse.json({ error: 'Failed to execute screener query' }, { status: 500 });
  }
}
