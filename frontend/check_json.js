const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });
async function check() {
  const [rows] = await bq.query('SELECT * FROM `adk-mini-project.user_data.watchlist`');
  console.log(JSON.stringify(rows));
}
check();
