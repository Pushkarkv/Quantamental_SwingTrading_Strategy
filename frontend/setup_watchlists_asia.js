const { BigQuery } = require('@google-cloud/bigquery');
const bq = new BigQuery({ projectId: 'adk-mini-project' });

async function init() {
  try {
    console.log('Dropping old user_data dataset...');
    await bq.dataset('user_data').delete({ force: true }).catch(e => console.log('Dataset may not exist yet:', e.message));

    console.log('Creating user_data dataset in asia-south1...');
    await bq.createDataset('user_data', { location: 'asia-south1' });

    console.log('Creating watchlists table...');
    await bq.query({
      query: `
        CREATE TABLE \`adk-mini-project.user_data.watchlists\` (
          id STRING,
          username STRING,
          name STRING,
          created_at TIMESTAMP
        )
      `,
      location: 'asia-south1'
    });

    console.log('Creating watchlist_items table...');
    await bq.query({
      query: `
        CREATE TABLE \`adk-mini-project.user_data.watchlist_items\` (
          watchlist_id STRING,
          nse_symbol STRING,
          added_at TIMESTAMP
        )
      `,
      location: 'asia-south1'
    });

    console.log('Done!');
  } catch (e) {
    console.error('ERROR:', e.message);
  }
}
init();
