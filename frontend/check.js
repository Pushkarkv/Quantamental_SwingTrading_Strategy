const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });
async function check() {
  try {
    const [rows] = await bq.query('SELECT * FROM `adk-mini-project.user_data.watchlist`');
    console.log('ROWS:', rows);
  } catch (e) {
    console.error('ERROR:', e.message);
  }
}
check();
