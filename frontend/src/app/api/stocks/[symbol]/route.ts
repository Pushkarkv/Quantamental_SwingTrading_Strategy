import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

export async function GET(request: Request, { params }: { params: Promise<{ symbol: string }> }) {
  try {
    const symbol = (await params).symbol.toUpperCase();

    // 1. Fetch OHLCV data (last 1 year)
    const ohlcvQuery = `
      SELECT 
        FORMAT_DATE('%Y-%m-%d', date) as time,
        open, high, low, close, volume
      FROM \`adk-mini-project.technicals.daily_stock_price\`
      WHERE symbol = @symbol AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
      ORDER BY date ASC
    `;
    const ohlcv = await queryBigQuery(ohlcvQuery, { symbol });

    // 2. Fetch latest prediction
    const predictionQuery = `
      SELECT 
        price_on_t0_inr, 
        predicted_upside_inr, 
        predicted_downside_inr, 
        predicted_avg_inr, 
        FORMAT_DATE('%Y-%m-%d', prediction_date) as prediction_date,
        FORMAT_DATE('%Y-%m-%d', board_meeting_date) as board_meeting_date, 
        risk_probability, 
        risk_flag_balanced_0_50
      FROM \`adk-mini-project.predictions.daily_inference_results\`
      WHERE nse_symbol = @symbol
      ORDER BY prediction_date DESC 
      LIMIT 1
    `;
    const predictions = await queryBigQuery(predictionQuery, { symbol });

    // 3. Fetch fundamentals
    const fundamentalsQuery = `
      SELECT 
        c.description as company_description, 
        c.sector_classification, 
        k.Stock_P_E as pe_ratio, 
        k.ROCE as roce, 
        k.ROE as roe, 
        k.Dividend_Yield as dividend_yield
      FROM \`adk-mini-project.fundamentals.company_info\` c
      LEFT JOIN \`adk-mini-project.fundamentals.key_ratios\` k ON c.nse_symbol = k.nse_symbol
      WHERE c.nse_symbol = @symbol
      LIMIT 1
    `;
    const fundamentals = await queryBigQuery(fundamentalsQuery, { symbol });

    return NextResponse.json({
      ohlcv,
      prediction: predictions.length > 0 ? predictions[0] : null,
      fundamentals: fundamentals.length > 0 ? fundamentals[0] : null
    });

  } catch (error) {
    console.error('API Error fetching stock detail:', error);
    return NextResponse.json({ error: 'Failed to fetch stock detail data' }, { status: 500 });
  }
}
