const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });

async function init() {
  try {
    console.log('Dropping old watchlist table if exists...');
    await bq.query('DROP TABLE IF EXISTS `adk-mini-project.user_data.watchlist`');

    console.log('Creating watchlists table...');
    await bq.query(`
      CREATE TABLE IF NOT EXISTS \`adk-mini-project.user_data.watchlists\` (
        id STRING,
        username STRING,
        name STRING,
        created_at TIMESTAMP
      )
    `);

    console.log('Creating watchlist_items table...');
    await bq.query(`
      CREATE TABLE IF NOT EXISTS \`adk-mini-project.user_data.watchlist_items\` (
        watchlist_id STRING,
        nse_symbol STRING,
        added_at TIMESTAMP
      )
    `);

    console.log('Done!');
  } catch (e) {
    console.error('ERROR:', e.message);
  }
}
init();
