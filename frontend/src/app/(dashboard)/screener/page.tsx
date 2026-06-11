'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Search, Filter, SlidersHorizontal, Loader2, ArrowUpDown, ChevronRight, Save } from 'lucide-react';
import styles from './screener.module.css';

interface FilterState {
  minUpside: string;
  minAvgReturn: string;
  maxRiskProb: string;
  riskProfile: string;
  sector: string;
  maxPe: string;
  sortBy: string;
  sortDir: 'asc' | 'desc';
}

const defaultFilters: FilterState = {
  minUpside: '20',
  minAvgReturn: '5',
  maxRiskProb: '50',
  riskProfile: 'balanced',
  sector: 'all',
  maxPe: '',
  sortBy: 'predicted_avg_pct',
  sortDir: 'desc'
};

const sectors = [
  'all',
  'Financial Services',
  'Information Technology',
  'Fast Moving Consumer Goods',
  'Healthcare',
  'Consumer Discretionary',
  'Industrials',
  'Energy',
  'Telecommunication',
  'Commodities'
];

export default function ScreenerPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(true);

  const fetchResults = async (currentFilters: FilterState) => {
    setLoading(true);
    try {
      const res = await fetch('/api/screener', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentFilters)
      });
      if (res.ok) {
        const data = await res.json();
        setResults(data.results || []);
      }
    } catch (err) {
      console.error('Failed to fetch screener results', err);
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    fetchResults(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleApply = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    fetchResults(filters);
  };

  const handleSort = (col: string) => {
    const newDir: 'asc' | 'desc' = filters.sortBy === col && filters.sortDir === 'desc' ? 'asc' : 'desc';
    const newFilters = { ...filters, sortBy: col, sortDir: newDir };
    setFilters(newFilters);
    fetchResults(newFilters);
  };

  const loadPreset = (type: 'value' | 'growth' | 'safe') => {
    let preset = { ...defaultFilters };
    if (type === 'value') preset = { ...defaultFilters, maxPe: '20', minAvgReturn: '10' };
    if (type === 'growth') preset = { ...defaultFilters, minUpside: '40', riskProfile: 'lenient' };
    if (type === 'safe') preset = { ...defaultFilters, maxRiskProb: '30', riskProfile: 'balanced' };
    
    setFilters(preset);
    fetchResults(preset);
  };

  return (
    <div className={`fade-in ${styles.page}`}>
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h1>Stock Screener</h1>
          <p>Find your next swing trade using ML predictions and fundamental filters.</p>
        </div>
        <div className={styles.presetButtons}>
          <button className="btn btn-secondary" onClick={() => loadPreset('value')}>Deep Value</button>
          <button className="btn btn-secondary" onClick={() => loadPreset('growth')}>High Growth</button>
          <button className="btn btn-secondary" onClick={() => loadPreset('safe')}>Safe Haven</button>
          <button className="btn btn-primary" onClick={() => setShowFilters(!showFilters)}>
            <SlidersHorizontal size={16} /> Filters
          </button>
        </div>
      </div>

      <div className={styles.layout}>
        {/* Sidebar Filters */}
        <div className={`${styles.filterSidebar} ${showFilters ? styles.show : styles.hide}`}>
          <div className="card">
            <h3 className={styles.filterTitle}><Filter size={18} /> Criteria</h3>
            <form onSubmit={handleApply} className={styles.filterForm}>
              
              <div className={styles.fieldGroup}>
                <label>Min Upside Potential (%)</label>
                <input 
                  type="number" 
                  className="input" 
                  value={filters.minUpside} 
                  onChange={e => setFilters({...filters, minUpside: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Min Avg Target (%)</label>
                <input 
                  type="number" 
                  className="input" 
                  value={filters.minAvgReturn} 
                  onChange={e => setFilters({...filters, minAvgReturn: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Max Risk Probability (%)</label>
                <input 
                  type="number" 
                  className="input" 
                  max="100"
                  value={filters.maxRiskProb} 
                  onChange={e => setFilters({...filters, maxRiskProb: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Risk Flag strictness</label>
                <select 
                  className="input" 
                  value={filters.riskProfile} 
                  onChange={e => setFilters({...filters, riskProfile: e.target.value})}
                >
                  <option value="all">Any Risk</option>
                  <option value="balanced">Balanced ({'<='} 0.50)</option>
                  <option value="lenient">Lenient ({'<='} 0.55)</option>
                  <option value="aggressive">Aggressive ({'<='} 0.45)</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label>Max P/E Ratio</label>
                <input 
                  type="number" 
                  className="input" 
                  placeholder="e.g. 30"
                  value={filters.maxPe} 
                  onChange={e => setFilters({...filters, maxPe: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Sector</label>
                <select 
                  className="input" 
                  value={filters.sector} 
                  onChange={e => setFilters({...filters, sector: e.target.value})}
                >
                  {sectors.map(s => (
                    <option key={s} value={s}>{s === 'all' ? 'All Sectors' : s}</option>
                  ))}
                </select>
              </div>

              <button type="submit" className="btn btn-primary" style={{width: '100%', marginTop: '8px'}} disabled={loading}>
                {loading ? <Loader2 size={16} className="spinner" /> : <Search size={16} />} 
                {loading ? 'Searching...' : 'Run Screen'}
              </button>
            </form>
          </div>
        </div>

        {/* Results Area */}
        <div className={styles.resultsArea}>
          <div className={`card ${styles.tableCard}`}>
            <div className={styles.resultsHeader}>
              <h2>{results.length} Results Found</h2>
            </div>
            
            <div className={styles.tableWrapper}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Sector</th>
                    <th onClick={() => handleSort('current_price')} className={styles.sortable}>
                      Price {filters.sortBy === 'current_price' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('predicted_upside_pct')} className={styles.sortable}>
                      Upside {filters.sortBy === 'predicted_upside_pct' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('predicted_avg_pct')} className={styles.sortable}>
                      Avg Target {filters.sortBy === 'predicted_avg_pct' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('risk_probability')} className={styles.sortable}>
                      Risk Prob {filters.sortBy === 'risk_probability' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('pe_ratio')} className={styles.sortable}>
                      P/E {filters.sortBy === 'pe_ratio' && <ArrowUpDown size={12} />}
                    </th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={8} className={styles.loadingCell}>
                        <Loader2 size={24} className="spinner text-blue" />
                      </td>
                    </tr>
                  ) : results.length === 0 ? (
                    <tr>
                      <td colSpan={8} className={styles.emptyCell}>
                        No stocks match your criteria. Try adjusting the filters.
                      </td>
                    </tr>
                  ) : (
                    results.map((r, i) => (
                      <tr key={r.nse_symbol}>
                        <td>
                          <Link href={`/stock/${r.nse_symbol}`} className={styles.symbolLink}>
                            <strong>{r.nse_symbol}</strong>
                          </Link>
                        </td>
                        <td className="text-secondary" style={{maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                          {r.sector_classification?.split(' > ').pop() || 'N/A'}
                        </td>
                        <td className="mono">₹{r.current_price?.toFixed(1) || 'N/A'}</td>
                        <td className="text-green mono">{(r.predicted_upside_pct * 100).toFixed(1)}%</td>
                        <td className={`mono ${r.predicted_avg_pct >= 0 ? 'text-green' : 'text-red'}`}>
                          {(r.predicted_avg_pct * 100).toFixed(1)}%
                        </td>
                        <td className="mono">{(r.risk_probability * 100).toFixed(1)}%</td>
                        <td className="mono">{r.pe_ratio || 'N/A'}</td>
                        <td>
                          <Link href={`/stock/${r.nse_symbol}`} className="btn btn-ghost" style={{padding: '4px 8px'}}>
                            <ChevronRight size={16} />
                          </Link>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
