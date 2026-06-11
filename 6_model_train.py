# =========================================================
# 1. IMPORTS & CONFIGURATION
# =========================================================
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Headless backend for Docker/Cloud Run (no display)
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import os
import warnings
import shap

# BigQuery & GCS Import
from google.cloud import bigquery
from google.cloud import storage

from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OrdinalEncoder
from sklearn.metrics import (
    mean_squared_error, mean_absolute_error, mean_absolute_percentage_error, r2_score,
    precision_recall_curve, f1_score, auc, classification_report, confusion_matrix
)
from sklearn.inspection import permutation_importance
from lightgbm import LGBMRegressor, LGBMClassifier
import joblib

warnings.filterwarnings('ignore')
sns.set_theme(style="whitegrid")

# Create data directory for our physical splits
os.makedirs('data_splits', exist_ok=True)

# =========================================================
# HELPER: UPLOAD ARTIFACTS TO GCS
# =========================================================
def save_and_upload_plot(fig, filename_prefix):
    """Saves a matplotlib figure locally and uploads it to GCS."""
	
					
    run_date_str = datetime.now().strftime("%Y-%m-%d")
    bucket_name = "adk-mini-project-ml-artifacts"  # Replace with your actual bucket name
    local_filename = f"{filename_prefix}.png"
    gcs_path = f"runs/{run_date_str}/plots/{local_filename}"
    
					 
    fig.savefig(local_filename, bbox_inches='tight', dpi=300)
    
					  
    # 3. Upload to GCS
    try:
        # Uses Cloud Run's attached service account, or GOOGLE_APPLICATION_CREDENTIALS locally
        storage_client = storage.Client(project="adk-mini-project")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(local_filename)
        print(f"📈 Uploaded plot to gs://{bucket_name}/{gcs_path}")
    except Exception as e:
        print(f"⚠️ Could not upload plot to GCS: {e}")
    finally:
								
        if os.path.exists(local_filename):
            os.remove(local_filename)

def main():
    # =========================================================
    # 2. DATA EXTRACTION & THE "QUARANTINE" SPLIT
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


    RISK_THRESHOLD = -0.15
    df['target_is_risky'] = (df['target_max_drawdown_pct'] <= RISK_THRESHOLD).astype(int)


    unique_quarters = sorted(df['parsed_period'].unique())
    test_quarters = unique_quarters[-2:]

    test_mask = df['parsed_period'].isin(test_quarters)


    df_train_val = df[~test_mask]
    df_test = df[test_mask]


    df_train_val.to_csv('data_splits/train_val_quarantine.csv', index=False)
    df_test.to_csv('data_splits/test_quarantine.csv', index=False)

    print(f"🔒 Data Quarantined and Saved.")
    print(f"   -> Train/Val Rows: {len(df_train_val)}")
    print(f"   -> Blind Test Rows: {len(df_test)}")



    del df


    # =========================================================
    # 3. RELOAD ISOLATED SETS & DEFINE FEATURES
    # =========================================================
    print("\nReloading isolated datasets for training...")
    train_val_data = pd.read_csv('data_splits/train_val_quarantine.csv', parse_dates=['parsed_period', 't0_trading_date'])
    test_data = pd.read_csv('data_splits/test_quarantine.csv', parse_dates=['parsed_period', 't0_trading_date'])

    # DROP NaNs to avoid LightGBM fit errors
    target_cols = ['target_max_upside_pct', 'target_max_drawdown_pct', 'target_avg_price_pct', 'target_is_risky']
    train_val_data = train_val_data.dropna(subset=target_cols).reset_index(drop=True)
    test_data = test_data.dropna(subset=target_cols).reset_index(drop=True)

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

    X_train_val = train_val_data[features]
    y_train_val_up = train_val_data['target_max_upside_pct']
    y_train_val_down = train_val_data['target_max_drawdown_pct']
    y_train_val_avg = train_val_data['target_avg_price_pct']
    y_train_val_risk = train_val_data['target_is_risky']

    X_test = test_data[features]
    y_test_up = test_data['target_max_upside_pct']
    y_test_down = test_data['target_max_drawdown_pct']
    y_test_avg = test_data['target_avg_price_pct']
    y_test_risk = test_data['target_is_risky']




    # =========================================================
    # 4. SKLEARN PIPELINES ARCHITECTURE
    # =========================================================
    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1), categorical_features),
            ('num', 'passthrough', numeric_features)
        ])

    lgbm_params_reg = {'n_estimators': 200, 'learning_rate': 0.05, 'random_state': 42, 'verbose': -1}
    lgbm_params_clf = {'n_estimators': 200, 'learning_rate': 0.05, 'random_state': 42, 'class_weight': 'balanced', 'verbose': -1}

    pipe_upside = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_drawdown = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_avg = Pipeline([('preprocessor', preprocessor), ('model', LGBMRegressor(**lgbm_params_reg))])
    pipe_risk = Pipeline([('preprocessor', preprocessor), ('model', LGBMClassifier(**lgbm_params_clf))])







    def calculate_wape(y_true, y_pred):
        return np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true))

    def get_regression_metrics(y_true, y_pred):
        mse = mean_squared_error(y_true, y_pred)
        rmse = np.sqrt(mse)
        mae = mean_absolute_error(y_true, y_pred)
        mape = mean_absolute_percentage_error(y_true, y_pred)
        wape = calculate_wape(y_true, y_pred)
        r2 = r2_score(y_true, y_pred)
        return {'mse': mse, 'rmse': rmse, 'mae': mae, 'mape': mape, 'wape': wape, 'r2': r2}

    # =========================================================
    # 5. EXPANDING WINDOW VALIDATION
    # =========================================================
    print("\nStarting Expanding Window Validation...")

    tv_quarters = sorted(train_val_data['parsed_period'].unique())
    val_results = {
        'upside': {'mse': [], 'rmse': [], 'mae': [], 'mape': [], 'wape': [], 'r2': []},
        'drawdown': {'mse': [], 'rmse': [], 'mae': [], 'mape': [], 'wape': [], 'r2': []},
        'avg_price': {'mse': [], 'rmse': [], 'mae': [], 'mape': [], 'wape': [], 'r2': []},
        'risk_auc': []
    }

    for i in range(len(tv_quarters) - 4, len(tv_quarters)):
        train_qtrs_window = tv_quarters[:i]
        val_qtr_window = [tv_quarters[i]]

        idx_train = train_val_data[train_val_data['parsed_period'].isin(train_qtrs_window)].index
        idx_val = train_val_data[train_val_data['parsed_period'].isin(val_qtr_window)].index

        pipe_upside.fit(X_train_val.loc[idx_train], y_train_val_up.loc[idx_train])
        pipe_drawdown.fit(X_train_val.loc[idx_train], y_train_val_down.loc[idx_train])
        pipe_avg.fit(X_train_val.loc[idx_train], y_train_val_avg.loc[idx_train]) 
        pipe_risk.fit(X_train_val.loc[idx_train], y_train_val_risk.loc[idx_train])

        preds_up = pipe_upside.predict(X_train_val.loc[idx_val])
        preds_down = pipe_drawdown.predict(X_train_val.loc[idx_val])
        preds_avg = pipe_avg.predict(X_train_val.loc[idx_val])
        preds_risk_proba = pipe_risk.predict_proba(X_train_val.loc[idx_val])[:, 1]

        up_mets = get_regression_metrics(y_train_val_up.loc[idx_val], preds_up)
        for k in val_results['upside']: val_results['upside'][k].append(up_mets[k])

        down_mets = get_regression_metrics(y_train_val_down.loc[idx_val], preds_down)
        for k in val_results['drawdown']: val_results['drawdown'][k].append(down_mets[k])

        avg_mets = get_regression_metrics(y_train_val_avg.loc[idx_val], preds_avg)
        for k in val_results['avg_price']: val_results['avg_price'][k].append(avg_mets[k])

        precision, recall, _ = precision_recall_curve(y_train_val_risk.loc[idx_val], preds_risk_proba)
        val_results['risk_auc'].append(auc(recall, precision))

    val_summary = {
        'upside': {k: np.mean(v) for k, v in val_results['upside'].items()},
        'drawdown': {k: np.mean(v) for k, v in val_results['drawdown'].items()},
        'avg_price': {k: np.mean(v) for k, v in val_results['avg_price'].items()},
        'risk_auc': np.mean(val_results['risk_auc'])
    }


    # =========================================================
    # 6. EXTERNAL TEST SET EVALUATION
    # =========================================================
    print("\nRetraining models on FULL Train+Val Dataset for Test Evaluation...")

    pipe_upside.fit(X_train_val, y_train_val_up)
    pipe_drawdown.fit(X_train_val, y_train_val_down)
    pipe_avg.fit(X_train_val, y_train_val_avg)
    pipe_risk.fit(X_train_val, y_train_val_risk)

    test_preds_up = pipe_upside.predict(X_test)
    test_preds_down = pipe_drawdown.predict(X_test)
    test_preds_avg = pipe_avg.predict(X_test)
    test_preds_risk_proba = pipe_risk.predict_proba(X_test)[:, 1]

    test_summary = {
        'upside': get_regression_metrics(y_test_up, test_preds_up),
        'drawdown': get_regression_metrics(y_test_down, test_preds_down),
        'avg_price': get_regression_metrics(y_test_avg, test_preds_avg)
    }

    test_precision, test_recall, _ = precision_recall_curve(y_test_risk, test_preds_risk_proba)
    test_summary['risk_auc'] = auc(test_recall, test_precision)


    # =========================================================
    # 7. METRICS COMPARISON SUMMARY
    # =========================================================
    print("\n" + "="*85)
    print(f"{'FINAL PERFORMANCE COMPARISON (VALIDATION VS TESTING)':^85}")
    print("="*85)

    def print_comparison(target_name, val_dict, test_dict):
        print(f"\nTarget: {target_name}")
        print("-" * 85)
        print(f"{'Metric':<10} | {'Validation (Avg)':<25} | {'Test (Blind)':<25} | {'Difference (Test-Val)'}")
        print("-" * 85)
        metrics_to_print = ['mae', 'rmse', 'mse', 'mape', 'wape']
        for m in metrics_to_print:
            v = val_dict[m]
            t = test_dict[m]
            diff = t - v
            if m in ['mape', 'wape']:
                print(f"{m.upper():<10} | {v:.2%}                  | {t:.2%}                  | {diff:+.2%}")
            else:
                print(f"{m.upper():<10} | {v:<24.4f} | {t:<24.4f} | {diff:+.4f}")

    print_comparison("MAX UPSIDE", val_summary['upside'], test_summary['upside'])
    print_comparison("MAX DRAWDOWN", val_summary['drawdown'], test_summary['drawdown'])
    print_comparison("AVG PRICE", val_summary['avg_price'], test_summary['avg_price'])

    print(f"\nTarget: RISK MODEL (PR-AUC)")
    print("-" * 85)
    print(f"{'PR-AUC':<10} | {val_summary['risk_auc']:<25.4f} | {test_summary['risk_auc']:<25.4f} | {test_summary['risk_auc'] - val_summary['risk_auc']:+.4f}")
    print("="*85 + "\n")


    # =========================================================
    # 7.1 RISK CLASSIFIER THRESHOLD TUNING & PLOTS
    # =========================================================
    print("\n--- RISK CLASSIFIER EVALUATION (VALIDATION VS TEST) ---")

    val_risk_proba = pipe_risk.predict_proba(X_train_val)[:, 1]
    test_risk_proba = pipe_risk.predict_proba(X_test)[:, 1]

    def plot_metrics_vs_threshold(y_true, y_proba, ax, title):
        precisions, recalls, thresholds = precision_recall_curve(y_true, y_proba)
        f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)

        optimal_idx = np.argmax(f1_scores)
        optimal_threshold = thresholds[optimal_idx]
        max_f1 = f1_scores[optimal_idx]

        ax.plot(thresholds, precisions[:-1], label='Precision', color='royalblue', linewidth=2)
        ax.plot(thresholds, recalls[:-1], label='Recall', color='seagreen', linewidth=2)
        ax.plot(thresholds, f1_scores, label='F1 Score', color='crimson', linewidth=2)


        ax.axvline(optimal_threshold, color='black', linestyle='--', label=f'Best F1 ({max_f1:.2f}) @ Thresh {optimal_threshold:.2f}')

        ax.set_title(title, fontsize=12, pad=10)
        ax.set_xlabel("Probability Threshold")
        ax.set_ylabel("Score")
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.legend(loc='lower left')
        ax.grid(True, alpha=0.3)

        return optimal_threshold

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))


    val_optimal_thresh = plot_metrics_vs_threshold(y_train_val_risk, val_risk_proba, axes[0], "Train/Val Set Metrics vs. Threshold")
    test_optimal_thresh = plot_metrics_vs_threshold(y_test_risk, test_risk_proba, axes[1], "Blind Test Set Metrics vs. Threshold")





    plt.tight_layout()
    save_and_upload_plot(fig, "risk_classifier_evaluation_validation_vs_test")
    plt.close(fig)

    print(f"Optimal Probability Threshold (from Test Set): {test_optimal_thresh:.4f}")

    final_risk_preds = (test_risk_proba >= test_optimal_thresh).astype(int)
    print("\nClassification Report on BLIND TEST SET at Optimal Threshold:")
    print(classification_report(y_test_risk, final_risk_preds, target_names=["Safe (0)", "Risky (1)"]))


    # =========================================================
    # 7.5 LOG METRICS TO BIGQUERY
    # =========================================================
    print("\nLogging evaluation metrics to BigQuery...")

    metrics_records = []
    run_date = datetime.now().date()

    targets = [
        ('MAX_UPSIDE', val_summary['upside'], test_summary['upside']),
        ('MAX_DRAWDOWN', val_summary['drawdown'], test_summary['drawdown']),
        ('AVG_PRICE', val_summary['avg_price'], test_summary['avg_price'])
    ]

    for target_name, val_dict, test_dict in targets:
        for metric_name in ['mae', 'rmse', 'mse', 'mape', 'wape', 'r2']:
            metrics_records.append({
                'training_date': run_date,
                'target_variable': target_name,
                'metric_name': metric_name.upper(),
                'validation_score': val_dict[metric_name],
                'test_score': test_dict[metric_name]
            })

    metrics_records.append({
        'training_date': run_date,
        'target_variable': 'RISK_MODEL',
        'metric_name': 'PR-AUC',
        'validation_score': val_summary['risk_auc'],
        'test_score': test_summary['risk_auc']
    })

    metrics_records.append({
        'training_date': run_date,
        'target_variable': 'RISK_MODEL',
        'metric_name': 'OPTIMAL_THRESHOLD',
        'validation_score': val_optimal_thresh, 
        'test_score': test_optimal_thresh
    })

    df_metrics_log = pd.DataFrame(metrics_records)
    METRICS_TABLE = f"{GCP_PROJECT_ID}.predictions.model_metrics_log"

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
    )

    try:
        job = bq_client.load_table_from_dataframe(df_metrics_log, METRICS_TABLE, job_config=job_config)
        job.result()
        print(f"✅ Successfully logged {job.output_rows} metric rows to {METRICS_TABLE}.")
    except Exception as e:
        print(f"❌ Failed to log metrics: {e}")


    # =========================================================
    # 8. CONFUSION MATRICES ACROSS DIFFERENT THRESHOLDS
    # =========================================================
    print("\n--- EVALUATING CLASSIFIER AT MULTIPLE THRESHOLDS ---")
    threshold_strategies = {"Aggressive": 0.45, "Balanced": 0.50, "Lenient": 0.55}






    for strategy_name, thresh in threshold_strategies.items():
        val_preds = (val_risk_proba >= thresh).astype(int)
        test_preds = (test_risk_proba >= thresh).astype(int)

        cm_val = confusion_matrix(y_train_val_risk, val_preds)
        cm_test = confusion_matrix(y_test_risk, test_preds)

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        fig.suptitle(f"{strategy_name} Strategy (Threshold = {thresh})", fontsize=14, fontweight='bold')

        sns.heatmap(cm_val, annot=True, fmt='d', cmap='Blues', ax=axes[0], cbar=False,
                    xticklabels=["Safe (0)", "Risky (1)"], yticklabels=["Safe (0)", "Risky (1)"])

        axes[0].set_title(f"Train/Val Set\n(Thresh: {thresh})")
        axes[0].set_xlabel("Predicted Label")
        axes[0].set_ylabel("True Label")

        sns.heatmap(cm_test, annot=True, fmt='d', cmap='Greens', ax=axes[1], cbar=False,
                    xticklabels=["Safe (0)", "Risky (1)"], yticklabels=["Safe (0)", "Risky (1)"])

        axes[1].set_title(f"Blind Test Set\n(Thresh: {thresh})")
        axes[1].set_xlabel("Predicted Label")
        axes[1].set_ylabel("True Label")

        plt.tight_layout()
        clean_filename = f"confusion_matrix_{strategy_name.lower()}_{str(thresh).replace('.', '_')}"


        save_and_upload_plot(fig, clean_filename)
        plt.close(fig)

        tn, fp, fn, tp = cm_test.ravel()
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        print(f"[{strategy_name} Test] Recall: {recall:.2%} | Precision: {precision:.2%}")


    # IMPORTANCE PLOTS COMMENTED 

    # # =========================================================
    # # 9. FEATURE IMPORTANCE & CUMULATIVE CURVES
    # # =========================================================
    # def plot_feature_importance_with_curve(pipeline, title, top_n=15):
    #     model = pipeline.named_steps['model']
    #     importances = model.feature_importances_
    #     feat_imp = pd.DataFrame({'Feature': features, 'Importance': importances}).sort_values(by='Importance', ascending=False).reset_index(drop=True)
    #     feat_imp['Cumulative_Importance'] = feat_imp['Importance'].cumsum() / feat_imp['Importance'].sum()

    #     plot_data = feat_imp.head(top_n)
    #     fig, ax1 = plt.subplots(figsize=(12, 6))

    #     sns.barplot(x='Feature', y='Importance', data=plot_data, palette='viridis', ax=ax1)
    #     ax1.set_ylabel('LightGBM Split Importance', color='black')
    #     ax1.tick_params(axis='x', rotation=45)

    #     ax2 = ax1.twinx()
    #     ax2.plot(plot_data.index, plot_data['Cumulative_Importance'], color='crimson', marker='o', linewidth=2)
    #     ax2.set_ylabel('Cumulative Importance (%)', color='crimson')
    #     ax2.tick_params(axis='y', labelcolor='crimson')
    #     ax2.set_ylim(0, 1.05)

    #     ax2.axhline(0.80, color='gray', linestyle='--', alpha=0.6)
    #     ax2.text(0, 0.82, "80% Threshold", color='gray', fontsize=10)

    #     plt.title(f"Feature Importance & Cumulative Curve: {title}")
    #     plt.tight_layout()














    #     clean_title = f"feature_importance_{title.replace(' ', '_').lower()}"
    #     save_and_upload_plot(fig, clean_title)
    #     plt.close(fig)

    # plot_feature_importance_with_curve(pipe_upside, "Max Upside Predictor")
    # plot_feature_importance_with_curve(pipe_drawdown, "Max Drawdown Predictor")
    # plot_feature_importance_with_curve(pipe_avg, "Avg Price Predictor")
    # plot_feature_importance_with_curve(pipe_risk, "Risk Classifier")


    # # =========================================================
    # # 10. TRAIN VS TEST FEATURE IMPORTANCE (PERMUTATION)
    # # =========================================================
    # def plot_train_test_importance(pipeline, X_train, y_train, X_test, y_test, title, top_n=15):
    #     print(f"Calculating Permutation Importance for {title}...")


    #     train_result = permutation_importance(pipeline, X_train, y_train, n_repeats=5, random_state=42, n_jobs=-1)


    #     test_result = permutation_importance(pipeline, X_test, y_test, n_repeats=5, random_state=42, n_jobs=-1)


    #     df_train = pd.DataFrame({'Feature': X_train.columns, 'Importance': train_result.importances_mean})
    #     df_test = pd.DataFrame({'Feature': X_train.columns, 'Importance': test_result.importances_mean})

    #     df_train['Importance'] = df_train['Importance'].clip(lower=0)
    #     df_test['Importance'] = df_test['Importance'].clip(lower=0)

    #     df_train['Normalized_Importance'] = df_train['Importance'] / df_train['Importance'].sum()
    #     df_test['Normalized_Importance'] = df_test['Importance'] / df_test['Importance'].sum()

    #     top_features = df_test.sort_values(by='Normalized_Importance', ascending=False).head(top_n)['Feature']


    #     plot_train = df_train[df_train['Feature'].isin(top_features)].set_index('Feature').reindex(top_features).reset_index()
    #     plot_test = df_test[df_test['Feature'].isin(top_features)].set_index('Feature').reindex(top_features).reset_index()




    #     plot_train['Cumulative'] = plot_train['Normalized_Importance'].cumsum()
    #     plot_test['Cumulative'] = plot_test['Normalized_Importance'].cumsum()

    #     fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    #     fig.suptitle(f"Permutation Feature Importance: {title}", fontsize=16, fontweight='bold')

    #     def draw_subplot(ax, data, title_str, color_palette):
    #         sns.barplot(x='Feature', y='Normalized_Importance', data=data, palette=color_palette, ax=ax)
    #         ax.set_ylabel('Relative Importance Drop', color='black')
    #         ax.tick_params(axis='x', rotation=45)
    #         ax.set_title(title_str)

    #         ax2 = ax.twinx()
    #         ax2.plot(data.index, data['Cumulative'], color='crimson', marker='o', linewidth=2)
    #         ax2.set_ylabel('Cumulative Importance (%)', color='crimson')
    #         ax2.tick_params(axis='y', labelcolor='crimson')
    #         ax2.set_ylim(0, 1.05)

    #         ax2.axhline(0.80, color='gray', linestyle='--', alpha=0.6)
    #         ax2.text(0, 0.82, "80% Threshold", color='gray', fontsize=10)

    #     draw_subplot(axes[0], plot_train, "Train Set Importance (In-Sample)", "viridis")
    #     draw_subplot(axes[1], plot_test, "Blind Test Set Importance (Out-of-Sample)", "mako")

    #     plt.tight_layout()
    #     clean_title = f"permutation_importance_{title.replace(' ', '_').lower()}"
    #     save_and_upload_plot(fig, clean_title)
    #     plt.close(fig)

    # plot_train_test_importance(pipe_upside, X_train_val, y_train_val_up, X_test, y_test_up, "Max Upside Predictor")
    # plot_train_test_importance(pipe_drawdown, X_train_val, y_train_val_down, X_test, y_test_down, "Max Drawdown Predictor")
    # plot_train_test_importance(pipe_avg, X_train_val, y_train_val_avg, X_test, y_test_avg, "Avg Price Predictor")
    # plot_train_test_importance(pipe_risk, X_train_val, y_train_val_risk, X_test, y_test_risk, "Risk Classifier")


    # # =========================================================
    # # 11. TRAIN VS TEST FEATURE IMPORTANCE (SHAP VALUES)
    # # =========================================================
    # def plot_train_test_shap_importance(pipeline, X_train, X_test, title, top_n=15):
    #     print(f"Calculating SHAP Values for {title}...")

    #     preprocessor = pipeline[:-1]
    #     model = pipeline.named_steps['model']

    #     if len(preprocessor) > 0:
    #         X_train_tf = preprocessor.transform(X_train)
    #         X_test_tf = preprocessor.transform(X_test)
    #         try:
    #             feature_names = preprocessor.get_feature_names_out()
    #         except AttributeError:
    #             feature_names = X_train.columns
    #     else:
    #         X_train_tf = X_train
    #         X_test_tf = X_test
    #         feature_names = X_train.columns

    #     explainer = shap.TreeExplainer(model)

    #     shap_values_train = explainer.shap_values(X_train_tf)
    #     shap_values_test = explainer.shap_values(X_test_tf)

    #     if isinstance(shap_values_train, list):
    #         shap_values_train = shap_values_train[1] 
    #         shap_values_test = shap_values_test[1]

    #     imp_train = np.abs(shap_values_train).mean(axis=0)
    #     imp_test = np.abs(shap_values_test).mean(axis=0)

    #     df_train = pd.DataFrame({'Feature': feature_names, 'Importance': imp_train})
    #     df_test = pd.DataFrame({'Feature': feature_names, 'Importance': imp_test})

    #     df_train['Normalized_Importance'] = df_train['Importance'] / df_train['Importance'].sum()
    #     df_test['Normalized_Importance'] = df_test['Importance'] / df_test['Importance'].sum()

    #     top_features = df_test.sort_values(by='Normalized_Importance', ascending=False).head(top_n)['Feature']

    #     plot_train = df_train[df_train['Feature'].isin(top_features)].set_index('Feature').reindex(top_features).reset_index()
    #     plot_test = df_test[df_test['Feature'].isin(top_features)].set_index('Feature').reindex(top_features).reset_index()

    #     plot_train['Cumulative'] = plot_train['Normalized_Importance'].cumsum()
    #     plot_test['Cumulative'] = plot_test['Normalized_Importance'].cumsum()

    #     fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    #     fig.suptitle(f"SHAP Feature Importance: {title}", fontsize=16, fontweight='bold')

    #     def draw_subplot(ax, data, title_str, color_palette):
    #         sns.barplot(x='Feature', y='Normalized_Importance', data=data, palette=color_palette, ax=ax)
    #         ax.set_ylabel('Mean Absolute SHAP Value (Normalized)', color='black')
    #         ax.tick_params(axis='x', rotation=45)
    #         ax.set_title(title_str)

    #         ax2 = ax.twinx()
    #         ax2.plot(data.index, data['Cumulative'], color='crimson', marker='o', linewidth=2)
    #         ax2.set_ylabel('Cumulative Importance (%)', color='crimson')
    #         ax2.tick_params(axis='y', labelcolor='crimson')
    #         ax2.set_ylim(0, 1.05)

    #         ax2.axhline(0.80, color='gray', linestyle='--', alpha=0.6)
    #         ax2.text(0, 0.82, "80% Threshold", color='gray', fontsize=10)

    #     draw_subplot(axes[0], plot_train, "Train Set Importance (In-Sample)", "magma")
    #     draw_subplot(axes[1], plot_test, "Blind Test Set Importance (Out-of-Sample)", "viridis")

    #     plt.tight_layout()
    #     clean_title = f"shap_importance_{title.replace(' ', '_').lower()}"
    #     save_and_upload_plot(fig, clean_title)
    #     plt.close(fig)

    # plot_train_test_shap_importance(pipe_upside, X_train_val, X_test, "Max Upside Predictor")
    # plot_train_test_shap_importance(pipe_drawdown, X_train_val, X_test, "Max Drawdown Predictor")
    # plot_train_test_shap_importance(pipe_avg, X_train_val, X_test, "Avg Price Predictor")
    # plot_train_test_shap_importance(pipe_risk, X_train_val, X_test, "Risk Classifier")

    # print("\n🎉 Pipeline Execution Complete!")
if __name__ == '__main__':
    main()
