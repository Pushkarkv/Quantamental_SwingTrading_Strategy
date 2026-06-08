import { NextResponse } from 'next/server';
import { queryBigQuery } from '@/lib/bigquery';

export async function GET() {
  try {
    const query = `
      WITH LatestRun AS (
        SELECT run_id 
        FROM \`adk-mini-project.pipeline.execution_log\` 
        ORDER BY run_timestamp DESC 
        LIMIT 1
      )
      SELECT 
        script_name, 
        status, 
        duration_seconds, 
        error_message, 
        CAST(run_timestamp as STRING) as run_timestamp
      FROM \`adk-mini-project.pipeline.execution_log\`
      WHERE run_id = (SELECT run_id FROM LatestRun)
      ORDER BY script_order ASC
    `;

    const logs = await queryBigQuery(query);

    return NextResponse.json({ logs });

  } catch (error) {
    console.error('API Error:', error);
    return NextResponse.json({ error: 'Failed to fetch execution logs' }, { status: 500 });
  }
}
