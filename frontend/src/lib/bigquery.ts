import { BigQuery } from '@google-cloud/bigquery';

const PROJECT_ID = process.env.GCP_PROJECT_ID || 'adk-mini-project';

let bqClient: BigQuery;

export function getBigQueryClient(): BigQuery {
  if (!bqClient) {
    // On Vercel: parse the service account JSON from env var
    const credJson = process.env.GOOGLE_APPLICATION_CREDENTIALS_JSON;
    if (credJson) {
      const credentials = JSON.parse(credJson);
      bqClient = new BigQuery({
        projectId: PROJECT_ID,
        credentials,
      });
    } else {
      // Locally: uses GOOGLE_APPLICATION_CREDENTIALS env var or ADC
      bqClient = new BigQuery({ projectId: PROJECT_ID });
    }
  }
  return bqClient;
}

export async function queryBigQuery<T = Record<string, unknown>>(
  sql: string,
  params?: Record<string, unknown>
): Promise<T[]> {
  const client = getBigQueryClient();
  const options: { query: string; params?: Record<string, unknown> } = { query: sql };
  if (params) options.params = params;
  
  const [rows] = await client.query(options);
  return rows as T[];
}
