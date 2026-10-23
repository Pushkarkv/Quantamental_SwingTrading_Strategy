const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });
async function check() {
  const id = '0d7684b8-b5d8-462c-a6df-250d67297ffc';
  const username = 'admin';
  const [rows] = await bq.query({
    query: 'SELECT id FROM `adk-mini-project.user_data.watchlists` WHERE id = @id AND username = @username',
    params: { id, username }
  });
  console.log('CHECK USER:', rows);
}
check();
