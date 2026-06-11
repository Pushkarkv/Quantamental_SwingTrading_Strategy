import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const q = searchParams.get('q') || '';
    
    if (!q || q.length < 2) {
      return NextResponse.json({ results: [] });
    }

    const query = `
      SELECT nse_symbol, company_name 
      FROM \`adk-mini-project.stocks.all_listed_stocks\`
      WHERE LOWER(nse_symbol) LIKE LOWER(@q) OR LOWER(company_name) LIKE LOWER(@q)
      LIMIT 8
    `;

    const results = await queryBigQuery(query, { q: `%${q}%` });

    return NextResponse.json({ results });

  } catch (error) {
    console.error('Search API Error:', error);
    return NextResponse.json({ error: 'Failed to fetch search suggestions' }, { status: 500 });
  }
}
