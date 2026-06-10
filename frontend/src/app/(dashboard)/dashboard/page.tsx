'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { TrendingUp, TrendingDown, Shield, Clock, ArrowUpRight, AlertTriangle } from 'lucide-react';
import styles from './dashboard.module.css';

interface PredictionRow {
  nse_symbol: string;
  stock_name: string;
  sector_l2: string;
  predicted_upside_pct: number;
  predicted_downside_pct: number;
  predicted_avg_pct: number;
  risk_probability: number;
  risk_flag_balanced_0_50: number;
  prediction_date: string;
  price_on_t0_inr: number;
}

function formatPct(val: number): string {
  return `${(val * 100).toFixed(1)}%`;
}

function formatInr(val: number): string {
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

export default function DashboardPage() {
  const [topPicks, setTopPicks] = useState<PredictionRow[]>([]);
  const [stats, setStats] = useState({ total: 0, passing: 0, avgUpside: 0, lastRun: '' });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/stocks?limit=10&riskProfile=balanced');
        if (res.ok) {
          const data = await res.json();
          setTopPicks(data.stocks || []);
          setStats(data.stats || { total: 0, passing: 0, avgUpside: 0, lastRun: '' });
        }
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  return (
    <div className={`fade-in ${styles.page}`}>
      <div className={styles.pageHeader}>
        <h1>Dashboard</h1>
        <p className="text-secondary">ML-powered stock predictions · Updated daily at 8:00 AM IST</p>
      </div>

      {/* Stats Cards */}
      <div className={styles.statsGrid}>
        <div className={`card ${styles.statCard}`}>
          <div className={`${styles.statIcon} ${styles.iconBlue}`}>
            <TrendingUp size={20} />
          </div>
          <div>
            <p className={styles.statValue}>{loading ? '—' : stats.total}</p>
            <p className={styles.statLabel}>Stocks Analyzed</p>
          </div>
        </div>

        <div className={`card ${styles.statCard}`}>
          <div className={`${styles.statIcon} ${styles.iconGreen}`}>
            <Shield size={20} />
          </div>
          <div>
            <p className={styles.statValue}>{loading ? '—' : stats.passing}</p>
            <p className={styles.statLabel}>Pass Filters</p>
          </div>
        </div>

        <div className={`card ${styles.statCard}`}>
          <div className={`${styles.statIcon} ${styles.iconGold}`}>
            <ArrowUpRight size={20} />
          </div>
          <div>
            <p className={styles.statValue}>{loading ? '—' : formatPct(stats.avgUpside)}</p>
            <p className={styles.statLabel}>Avg Upside</p>
          </div>
        </div>

        <div className={`card ${styles.statCard}`}>
          <div className={`${styles.statIcon} ${styles.iconPurple}`}>
            <Clock size={20} />
          </div>
          <div>
            <p className={styles.statValue}>{loading ? '—' : stats.lastRun || 'N/A'}</p>
            <p className={styles.statLabel}>Last Pipeline Run</p>
          </div>
        </div>
      </div>

      {/* Top Picks Table */}
      <div className={`card ${styles.tableCard}`}>
        <div className={styles.tableHeader}>
          <h2>🎯 Top Picks</h2>
          <Link href="/screener" className="btn btn-ghost" style={{ fontSize: '0.8rem' }}>
            View All →
          </Link>
        </div>

        {loading ? (
          <div className={styles.loadingRows}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className={`skeleton ${styles.skeletonRow}`} />
            ))}
          </div>
        ) : topPicks.length === 0 ? (
          <div className={styles.emptyState}>
            <AlertTriangle size={32} className="text-muted" />
            <p>No predictions available yet. Run the pipeline first.</p>
          </div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Sector</th>
                  <th>Price</th>
                  <th>Upside</th>
                  <th>Downside</th>
                  <th>Avg Return</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {topPicks.map((stock) => (
                  <tr key={stock.nse_symbol}>
                    <td>
                      <Link href={`/stock/${stock.nse_symbol}`} className={styles.symbolLink}>
                        <span className={styles.symbol}>{stock.nse_symbol}</span>
                        <span className={styles.stockName}>{stock.stock_name}</span>
                      </Link>
                    </td>
                    <td className="text-secondary">{stock.sector_l2}</td>
                    <td className="mono">{formatInr(stock.price_on_t0_inr)}</td>
                    <td>
                      <span className="badge badge-green">
                        <TrendingUp size={12} />
                        {formatPct(stock.predicted_upside_pct)}
                      </span>
                    </td>
                    <td>
                      <span className="badge badge-red">
                        <TrendingDown size={12} />
                        {formatPct(stock.predicted_downside_pct)}
                      </span>
                    </td>
                    <td className={stock.predicted_avg_pct >= 0 ? 'text-green mono' : 'text-red mono'}>
                      {formatPct(stock.predicted_avg_pct)}
                    </td>
                    <td>
                      <span className={`badge ${stock.risk_flag_balanced_0_50 === 0 ? 'badge-green' : 'badge-red'}`}>
                        {stock.risk_flag_balanced_0_50 === 0 ? 'Safe' : 'Risky'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
