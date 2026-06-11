const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });
async function check() {
  const [watchlists] = await bq.query('SELECT * FROM `adk-mini-project.user_data.watchlists`');
  console.log('WATCHLISTS:', watchlists);
  
  const [items] = await bq.query('SELECT * FROM `adk-mini-project.user_data.watchlist_items`');
  console.log('ITEMS:', items);
}
check();
