# =========================================================
# 1. IMPORTS & CONFIGURATION
# =========================================================
import os
import warnings
from datetime import datetime

import pandas as pd
import numpy as np
from scipy.stats import percentileofscore
import shap
import joblib

from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OrdinalEncoder
from sklearn.metrics import (
    mean_squared_error, mean_absolute_error, r2_score,
    precision_recall_curve, f1_score, auc, classification_report
)
from lightgbm import LGBMRegressor, LGBMClassifier

warnings.filterwarnings('ignore')

# Create data directories for our physical splits and models
os.makedirs('data_splits', exist_ok=True)
os.makedirs('saved_models', exist_ok=True)

def main():
    # =========================================================
    # 2. DATA EXTRACTION
    # =========================================================
    print("Extracting data from BigQuery...")

    GCP_PROJECT_ID = "adk-mini-project"

    # Uses Cloud Run's attached service account, or GOOGLE_APPLICATION_CREDENTIALS locally
    bq_client = bigquery.Client(project=GCP_PROJECT_ID)

    master_query = """
    SELECT * FROM `adk-mini-project.technicals.train_data`;
    """

    df = bq_client.query(master_query).to_dataframe() 

    print(f"Data Extracted. Total Rows: {len(df)}")

    df['parsed_period'] = pd.to_datetime(df['parsed_period'])
    df['t0_trading_date'] = pd.to_datetime(df['t0_trading_date'])
    df = df.sort_values(by='t0_trading_date').reset_index(drop=True)

    # Define Risk Target
    RISK_THRESHOLD = -0.15
    df['target_is_risky'] = (df['target_max_drawdown_pct'] <= RISK_THRESHOLD).astype(int)

    # =========================================================
    # 3. FIX PERCENTILE SKEW FOR UNCONCLUDED QUARTER
    # =========================================================
    print("\nFixing percentile skew for unconcluded quarter peers...")

    unique_quarters = sorted(df['parsed_period'].unique())
    q_unconcluded = unique_quarters[-1]
    q_prev = unique_quarters[-2] if len(unique_quarters) > 1 else q_unconcluded

    # Features that need recalculating against previous quarter's distribution
    percentile_features = [
        'npm_sector_l2_percentile',
        'rev_growth_yoy_l2_percentile',
        'roce_sector_l2_percentile'
    ]
    metrics = [
        'net_profit_margin_pct',
        'rev_growth_yoy',
        'roce_pct'
    ]

    df_prev = df[df['parsed_period'] == q_prev]
    mask_unconcluded = (df['parsed_period'] == q_unconcluded)

    for sector in df.loc[mask_unconcluded, 'sector_l2'].unique():
        sector_prev_dist = df_prev[df_prev['sector_l2'] == sector]
        sector_curr_mask = mask_unconcluded & (df['sector_l2'] == sector)

        for pct_feat, metric in zip(percentile_features, metrics):
            prev_vals = sector_prev_dist[metric].dropna().values

            if len(prev_vals) > 0:
                def calc_percentile(val):
                    if pd.isna(val):
                        return np.nan
                    return percentileofscore(prev_vals, val) / 100.0

                df.loc[sector_curr_mask, pct_feat] = df.loc[sector_curr_mask, metric].apply(calc_percentile)

    print("✅ Percentiles adjusted using historical peer distributions.")

    # =========================================================
    # 4. DATA SPLITTING (Historical vs Inference)
    # =========================================================
    # The "unconcluded" quarter is completely isolated for inference.
    inference_mask = df['parsed_period'] == q_unconcluded
    historical_mask = ~inference_mask

    # We also exclude rows in historical data that have null targets to be safe
    historical_mask = historical_mask & df['target_max_upside_pct'].notna()

    df_historical = df[historical_mask].copy()
    df_inference = df[inference_mask].copy()

    # Save physically to disk
    df_historical.to_csv('data_splits/historical_data.csv', index=False)
    df_inference.to_csv('data_splits/inference_data.csv', index=False)

    print(f"🔒 Data Split and Saved.")
    print(f"   -> Historical Rows (Training): {len(df_historical)}")
    print(f"   -> Inference Rows: {len(df_inference)}")
    print(f"   -> Inference Quarter: {q_unconcluded.strftime('%Y-%m')}")

    # Define Features and Targets
    categorical_features = ['sector_l2', 'sector_l3']
    numeric_features = [
        'ttm_revenue', 'historical_pe', 'historical_market_cap', 
        'op_margin_pct', 'net_profit_margin_pct', 'rev_growth_yoy', 
        'eps_growth_yoy', 'fii_change_qoq', 'dii_change_qoq', 'promoter_change_qoq',
        'cfo_to_net_profit_ratio', 'cash_conversion_cycle_days', 'roce_pct',
        'dist_from_200sma', 'natr_14d', 'obv_90d_slope_norm', 'return_90d', 
        'historical_peg', 'historical_ps', 'rs_90d_percentile', 
        'npm_sector_l2_percentile', 'rev_growth_yoy_l2_percentile', 'roce_sector_l2_percentile'
    ]
    features = categorical_features + numeric_features

    X_hist = df_historical[features]
    y_hist_up = df_historical['target_max_upside_pct']
    y_hist_down = df_historical['target_max_drawdown_pct']
    y_hist_avg = df_historical['target_avg_price_pct']
    y_hist_risk = df_historical['target_is_risky']

    X_infer = df_inference[features]

    # =========================================================
    # 5. SKLEARN PIPELINES ARCHITECTURE
    # =========================================================
    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1), categorical_features),
            ('num', 'passthrough', numeric_features)
        ])

    # Base LightGBM configurations
    lgbm_params_reg = {'n_estimators': 200, 'learning_rate': 0.05, 'random_state': 42, 'verbose': -1}
    lgbm_params_clf = {'n_estimators': 200, 'learning_rate': 0.05, 'random_state': 42, 'class_weight': 'balanced', 'verbose': -1}

    # Assemble Pipelines
    pipe_upside = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_drawdown = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_avg = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_risk = Pipeline([('preprocessor', preprocessor), ('model', LGBMClassifier(**lgbm_params_clf))])

    print("✅ LightGBM Pipelines Assembled.")

    # =========================================================
    # 6. EXPANDING WINDOW VALIDATION & FULL RETRAINING
    # =========================================================
    print("\nStarting Expanding Window Validation on Historical Data...")

    tv_quarters = sorted(df_historical['parsed_period'].unique())
    val_metrics = {'upside_rmse': [], 'drawdown_rmse': [], 'risk_auc': [], 'f1_thresholds': []}

    # Validate across the last 4 quarters of the historical set
    for i in range(len(tv_quarters) - 4, len(tv_quarters)):
        train_qtrs_window = tv_quarters[:i]
        val_qtr_window = [tv_quarters[i]]

        idx_train = df_historical[df_historical['parsed_period'].isin(train_qtrs_window)].index
        idx_val = df_historical[df_historical['parsed_period'].isin(val_qtr_window)].index

        pipe_upside.fit(X_hist.loc[idx_train], y_hist_up.loc[idx_train])
        pipe_drawdown.fit(X_hist.loc[idx_train], y_hist_down.loc[idx_train])
        pipe_risk.fit(X_hist.loc[idx_train], y_hist_risk.loc[idx_train])

        preds_up = pipe_upside.predict(X_hist.loc[idx_val])
        preds_down = pipe_drawdown.predict(X_hist.loc[idx_val])
        preds_risk_proba = pipe_risk.predict_proba(X_hist.loc[idx_val])[:, 1]

        val_metrics['upside_rmse'].append(np.sqrt(mean_squared_error(y_hist_up.loc[idx_val], preds_up)))
        val_metrics['drawdown_rmse'].append(np.sqrt(mean_squared_error(y_hist_down.loc[idx_val], preds_down)))

        precision, recall, thresholds = precision_recall_curve(y_hist_risk.loc[idx_val], preds_risk_proba)
        val_metrics['risk_auc'].append(auc(recall, precision))

        f1_scores = 2 * (precision * recall) / (precision + recall + 1e-9)
        if len(thresholds) > 0:
            val_metrics['f1_thresholds'].append(thresholds[np.argmax(f1_scores)])

    optimal_threshold = np.mean(val_metrics['f1_thresholds']) if val_metrics['f1_thresholds'] else 0.45

    print(f"📊 Avg Val Upside RMSE: {np.mean(val_metrics['upside_rmse']):.4f}")
    print(f"📊 Avg Val Drawdown RMSE: {np.mean(val_metrics['drawdown_rmse']):.4f}")
    print(f"📊 Avg Val Risk PR-AUC: {np.mean(val_metrics['risk_auc']):.4f}")
    print(f"📊 Optimal Risk Threshold (Mean of splits): {optimal_threshold:.4f}")

    print("\nRetraining final models on ENTIRE Historical Dataset...")
    pipe_upside.fit(X_hist, y_hist_up)
    pipe_drawdown.fit(X_hist, y_hist_down)
    pipe_avg.fit(X_hist, y_hist_avg)
    pipe_risk.fit(X_hist, y_hist_risk)
    print("✅ Final models trained and ready for inference.")

    # =========================================================
    # 6.5 SAVE TRAINED MODELS FOR FUTURE USE
    # =========================================================
    print("\nSaving trained models to disk...")

    # Save the regression pipelines
    joblib.dump(pipe_upside, 'saved_models/pipe_upside.joblib')
    joblib.dump(pipe_drawdown, 'saved_models/pipe_drawdown.joblib')
    joblib.dump(pipe_avg, 'saved_models/pipe_avg.joblib')

    # Save the classification pipeline
    joblib.dump(pipe_risk, 'saved_models/pipe_risk.joblib')

    # Save the calculated optimal threshold so it can be applied consistently later
    joblib.dump(optimal_threshold, 'saved_models/optimal_risk_threshold.joblib')

    print("✅ All models and the optimal risk threshold successfully saved in 'saved_models/' directory.")

    # =========================================================
    # 7. INFERENCE & DELTA BIGQUERY UPLOAD
    # =========================================================
    print(f"\nRunning Inference for Unconcluded Quarter: {q_unconcluded.strftime('%Y-%m')}")

    # 1. Run Predictions
    pred_up = pipe_upside.predict(X_infer)
    pred_down = pipe_drawdown.predict(X_infer)
    pred_avg = pipe_avg.predict(X_infer)
    pred_risk_proba = pipe_risk.predict_proba(X_infer)[:, 1]

    # 2. Assemble the NEW Prediction DataFrame
    bq_export_df = pd.DataFrame({
        'nse_symbol': df_inference['nse_symbol'],
        'stock_name': df_inference.get('Company_Name', 'N/A'), 
        'sector_l1': df_inference.get('sector_l1', 'N/A'),
        'sector_l2': df_inference['sector_l2'],
        'sector_l3': df_inference.get('sector_l3', 'N/A'),
        'sector_l4': df_inference.get('sector_l4', 'N/A'),

        'board_meeting_date': pd.to_datetime(df_inference.get('exact_t0_date', df_inference['t0_trading_date'])).dt.date,
        'prediction_for_quarter': df_inference['parsed_period'].dt.date,
        'prediction_date': datetime.now().date(),

        'price_on_t0_inr': df_inference['t0_close'],

        'predicted_upside_pct': pred_up,
        'predicted_downside_pct': pred_down,
        'predicted_avg_pct': pred_avg,

        'predicted_upside_inr': df_inference['t0_close'] * (1 + pred_up),
        'predicted_downside_inr': df_inference['t0_close'] * (1 + pred_down),
        'predicted_avg_inr': df_inference['t0_close'] * (1 + pred_avg),

        'risk_probability': pred_risk_proba,

        'risk_flag_aggressive_0_45': (pred_risk_proba >= 0.45).astype(int),
        'risk_flag_balanced_0_50': (pred_risk_proba >= 0.50).astype(int),
        'risk_flag_lenient_0_55': (pred_risk_proba >= 0.55).astype(int)
    })

    # Filter out rows with missing T0 prices
    bq_export_df = bq_export_df.dropna(subset=['price_on_t0_inr'])

    # =========================================================
    # DELTA LOGIC: Compare with existing BigQuery records
    # =========================================================
    DESTINATION_TABLE = f"{GCP_PROJECT_ID}.predictions.daily_inference_results"
    current_qtr_str = q_unconcluded.strftime('%Y-%m-%d')

    fetch_latest_query = f"""
        SELECT nse_symbol, predicted_upside_pct, predicted_downside_pct, risk_probability
        FROM `{DESTINATION_TABLE}`
        WHERE prediction_for_quarter = '{current_qtr_str}'
        QUALIFY ROW_NUMBER() OVER(PARTITION BY nse_symbol ORDER BY prediction_date DESC) = 1
    """

    try:
        print("Fetching existing predictions to check for updates...")
        existing_df = bq_client.query(fetch_latest_query).to_dataframe()

        # Merge new predictions with existing ones to compare
        comparison_df = bq_export_df.merge(
            existing_df, 
            on='nse_symbol', 
            how='left', 
            suffixes=('', '_old')
        )

        # Find rows where the stock is completely new (no old record)
        is_new_stock = comparison_df['predicted_upside_pct_old'].isna()

        # Find rows where the prediction has materially changed 
        has_changed = (
            (comparison_df['predicted_upside_pct'].round(4) != comparison_df['predicted_upside_pct_old'].round(4)) |
            (comparison_df['predicted_downside_pct'].round(4) != comparison_df['predicted_downside_pct_old'].round(4)) |
            (comparison_df['risk_probability'].round(4) != comparison_df['risk_probability_old'].round(4))
        )

        upload_mask = is_new_stock | has_changed

        # 👉 THE FIX: Filter the merged dataframe, then keep only the original columns
        final_upload_df = comparison_df[upload_mask][bq_export_df.columns].copy()

    except NotFound:
        # If the table doesn't exist yet (first time running), upload everything
        print("Table not found. This must be the first run. Uploading all rows.")
        final_upload_df = bq_export_df.copy()

    # =========================================================
    # BIGQUERY UPLOAD
    # =========================================================
    if len(final_upload_df) == 0:
        print("No new or changed predictions today. Skipping BigQuery upload.")
    else:
        print(f"Uploading {len(final_upload_df)} new/updated rows to {DESTINATION_TABLE}...")

        # Configure the load job with Partitioning
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, # Partitions by day
                field="prediction_date",                 # The column to partition on
                expiration_ms=None                       # Explicitly prevents deletion
            )
        )

        try:
            job = bq_client.load_table_from_dataframe(
                final_upload_df, 
                DESTINATION_TABLE, 
                job_config=job_config
            )
            job.result()
            print(f"✅ Successfully appended {job.output_rows} rows to BigQuery.")
        except Exception as e:
            print(f"❌ Failed to upload to BigQuery: {e}")

    # Display a quick preview of what was uploaded (if anything) using print instead of display
    if len(final_upload_df) > 0:
        print(final_upload_df.head())

    # =========================================================
    # 8. DELTA SHAP VALUE GENERATION & BIGQUERY UPLOAD
    # =========================================================
    print("\nChecking for SHAP value generation requirements...")

    def extract_shap_to_long_df(pipeline, X_subset, symbols, model_name, pred_date, quarter_date):
        """
        Calculates SHAP values for a subset of data and melts them into a BigQuery format.
        """
        preprocessor = pipeline[:-1]
        model = pipeline.named_steps['model']

        # Transform only the subset of data
        if len(preprocessor) > 0:
            X_tf = preprocessor.transform(X_subset)
            try:
                feature_names = preprocessor.get_feature_names_out()
            except AttributeError:
                feature_names = X_subset.columns
        else:
            X_tf = X_subset
            feature_names = X_subset.columns

        # Calculate SHAP Values
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_tf)

        # Handle LightGBM Classifier output
        if isinstance(shap_values, list):
            shap_values = shap_values[1] 

        # Build DataFrame
        shap_df = pd.DataFrame(shap_values, columns=feature_names)
        shap_df['nse_symbol'] = symbols.values

        # Melt into Long Format
        long_df = shap_df.melt(id_vars=['nse_symbol'], var_name='feature_name', value_name='shap_value')

        # Add Metadata
        long_df['prediction_date'] = pred_date
        long_df['prediction_for_quarter'] = quarter_date
        long_df['model_target'] = model_name

        # Drop rows where feature had zero impact to save DB space
        long_df = long_df[long_df['shap_value'] != 0]

        return long_df

    # Check if Block 7 actually flagged any rows for upload today
    if 'final_upload_df' in locals() and len(final_upload_df) > 0:

        current_date = datetime.now().date()
        current_quarter = df_inference['parsed_period'].dt.date.iloc[0]

        # 1. Isolate the specific stocks that had prediction changes today
        changed_symbols = final_upload_df['nse_symbol']
        print(f"Generating SHAP values for the {len(changed_symbols)} stocks that updated today...")

        # 2. Filter the original X_infer dataset to ONLY include these changed stocks
        mask_changed = df_inference['nse_symbol'].isin(changed_symbols)
        X_infer_changed = X_infer[mask_changed]

        # 3. Generate SHAP DataFrames for all 4 models using the filtered data
        shap_dfs = [
            extract_shap_to_long_df(pipe_upside, X_infer_changed, changed_symbols, 'max_upside', current_date, current_quarter),
            extract_shap_to_long_df(pipe_drawdown, X_infer_changed, changed_symbols, 'max_drawdown', current_date, current_quarter),
            extract_shap_to_long_df(pipe_avg, X_infer_changed, changed_symbols, 'avg_price', current_date, current_quarter),
            extract_shap_to_long_df(pipe_risk, X_infer_changed, changed_symbols, 'risk_classifier', current_date, current_quarter)
        ]

        final_shap_df = pd.concat(shap_dfs, ignore_index=True)

        bq_shap_schema = [
            'prediction_date', 'prediction_for_quarter', 'nse_symbol', 
            'model_target', 'feature_name', 'shap_value'
        ]
        final_shap_df = final_shap_df[bq_shap_schema]

        print(f"Prepared {len(final_shap_df)} delta SHAP value rows for BigQuery.")

        # 4. Upload to BigQuery
        SHAP_DESTINATION_TABLE = f"{GCP_PROJECT_ID}.predictions.daily_shap_values"
        print(f"Uploading SHAP values to {SHAP_DESTINATION_TABLE}...")

        # Configure the load job with Partitioning
        job_config_shap = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, # Partitions by day
                field="prediction_date",                 # The column to partition on
                expiration_ms=None                       # Explicitly prevents deletion
            )
        )

        try:
            shap_job = bq_client.load_table_from_dataframe(
                final_shap_df, 
                SHAP_DESTINATION_TABLE, 
                job_config=job_config_shap
            )
            shap_job.result()
            print(f"✅ Successfully appended {shap_job.output_rows} SHAP rows to BigQuery.")
        except Exception as e:
            print(f"❌ Failed to upload SHAP values to BigQuery: {e}")

    else:
        print("No new or changed predictions today. Skipping SHAP generation entirely to save compute.")
if __name__ == '__main__':
    main()
