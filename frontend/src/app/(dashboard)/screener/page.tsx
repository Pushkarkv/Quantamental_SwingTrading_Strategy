'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Search, Filter, SlidersHorizontal, Loader2, ArrowUpDown, ChevronRight, Save, Trash2 } from 'lucide-react';
import styles from './screener.module.css';

interface FilterState {
  minUpside: string;
  minAvgReturn: string;
  maxRiskProb: string;
  maxDrawdown: string;
  minRewardRisk: string;
  sectorL2: string;
  sectorL3: string;
  sortBy: string;
  sortDir: 'asc' | 'desc';
}

const defaultFilters: FilterState = {
  minUpside: '20',
  minAvgReturn: '5',
  maxRiskProb: '50',
  maxDrawdown: '',
  minRewardRisk: '',
  sectorL2: 'all',
  sectorL3: 'all',
  sortBy: 'predicted_avg_pct',
  sortDir: 'desc'
};

const sectorL2Options = [
  'all', 'Automobile and Auto Components', 'Capital Goods', 'Chemicals', 
  'Construction', 'Construction Materials', 'Consumer Durables', 'Consumer Services', 
  'Diversified', 'Fast Moving Consumer Goods', 'Financial Services', 'Forest Materials', 
  'Healthcare', 'Information Technology', 'Media, Entertainment & Publication', 
  'Metals & Mining', 'Oil, Gas & Consumable Fuels', 'Power', 'Realty', 'Services', 
  'Telecommunication', 'Textiles', 'Utilities'
];

const sectorL3Options = [
  'all', 'Aerospace & Defense', 'Chemicals & Petrochemicals', 'Cigarettes & Tobacco Products', 
  'Commercial Services & Supplies', 'Construction', 'Diversified', 'Diversified FMCG', 
  'Engineering Services', 'Ferrous Metals', 'Financial Technology (Fintech)', 'Gas', 
  'Industrial Manufacturing', 'Other Utilities', 'Paper, Forest & Jute Products', 'Power', 
  'Transport Infrastructure', 'Transport Services'
];

export default function ScreenerPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);
  const [allStocks, setAllStocks] = useState<any[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(true);
  
  const [savedPresets, setSavedPresets] = useState<any[]>([]);
  const [newPresetName, setNewPresetName] = useState('');
  const [isSavingPreset, setIsSavingPreset] = useState(false);
  const [showPercentage, setShowPercentage] = useState(true);

  const applyFilters = (stocksToFilter: any[], currentFilters: FilterState) => {
    let filtered = stocksToFilter.filter(p => {
      if (currentFilters.minUpside && (p.predicted_upside_pct * 100) < parseFloat(currentFilters.minUpside)) return false;
      if (currentFilters.minAvgReturn && (p.predicted_avg_pct * 100) < parseFloat(currentFilters.minAvgReturn)) return false;
      if (currentFilters.maxRiskProb && (p.risk_probability * 100) > parseFloat(currentFilters.maxRiskProb)) return false;
      
      if (currentFilters.maxDrawdown && (Math.abs(p.predicted_downside_pct || 0) * 100) > parseFloat(currentFilters.maxDrawdown)) return false;
      if (currentFilters.minRewardRisk) {
        const downside = Math.abs(p.predicted_downside_pct || 0);
        if (downside === 0) return false;
        const rr = (p.predicted_upside_pct || 0) / downside;
        if (rr < parseFloat(currentFilters.minRewardRisk)) return false;
      }

      if (currentFilters.sectorL2 !== 'all' && p.sector_l2 !== currentFilters.sectorL2) return false;
      if (currentFilters.sectorL3 !== 'all' && p.sector_l3 !== currentFilters.sectorL3) return false;

      return true;
    });

    const col = currentFilters.sortBy;
    const dir = currentFilters.sortDir;
    
    filtered.sort((a: any, b: any) => {
      let valA = a[col] ?? '';
      let valB = b[col] ?? '';
      if (typeof valA === 'string') return dir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      return dir === 'asc' ? valA - valB : valB - valA;
    });

    setResults(filtered);
  };

  const fetchAllStocks = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/screener');
      if (res.ok) {
        const data = await res.json();
        const fetchedResults = data.results || [];
        setAllStocks(fetchedResults);
        applyFilters(fetchedResults, filters);
      }
    } catch (err) {
      console.error('Failed to fetch screener results', err);
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    fetchAllStocks();
    fetchPresets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchPresets = async () => {
    try {
      const res = await fetch('/api/screener/presets');
      if (res.ok) {
        const data = await res.json();
        setSavedPresets(data.presets || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const savePreset = async () => {
    if (!newPresetName) return;
    setIsSavingPreset(true);
    try {
      const res = await fetch('/api/screener/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newPresetName, filters })
      });
      if (res.ok) {
        setNewPresetName('');
        fetchPresets();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsSavingPreset(false);
    }
  };

  const deletePreset = async (id: string) => {
    try {
      await fetch(`/api/screener/presets?id=${id}`, { method: 'DELETE' });
      fetchPresets();
    } catch (e) {
      console.error(e);
    }
  };

  const applyPreset = (presetFiltersStr: string) => {
    try {
      const parsed = JSON.parse(presetFiltersStr);
      setFilters(parsed);
      applyFilters(allStocks, parsed);
    } catch(e) {
      console.error("Invalid preset filters");
    }
  };

  const handleApply = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    applyFilters(allStocks, filters);
  };

  const handleSort = (col: string) => {
    const newDir: 'asc' | 'desc' = filters.sortBy === col && filters.sortDir === 'desc' ? 'asc' : 'desc';
    const newFilters = { ...filters, sortBy: col, sortDir: newDir };
    setFilters(newFilters);
    applyFilters(allStocks, newFilters);
  };

  const exportToCSV = () => {
    if (results.length === 0) return;
    const headers = [
      'Symbol', 'Sector L2', 'Sector L3', 'Current Price', 'T0 Price', 
      'Avg Target (%)', 'Avg Target (₹)', 
      'Upside (%)', 'Upside (₹)', 
      'Downside (%)', 'Downside (₹)', 
      'Risk Prob (%)'
    ];
    const csvContent = [
      headers.join(','),
      ...results.map(r => [
        r.nse_symbol,
        `"${r.sector_l2 || 'N/A'}"`,
        `"${r.sector_l3 || 'N/A'}"`,
        r.current_price?.toFixed(2) || 'N/A',
        r.t0_price?.toFixed(2) || 'N/A',
        ((r.predicted_avg_pct || 0) * 100).toFixed(2),
        r.t0_price ? (r.t0_price * (1 + (r.predicted_avg_pct || 0))).toFixed(2) : 'N/A',
        ((r.predicted_upside_pct || 0) * 100).toFixed(2),
        r.t0_price ? (r.t0_price * (1 + (r.predicted_upside_pct || 0))).toFixed(2) : 'N/A',
        ((r.predicted_downside_pct || 0) * 100).toFixed(2),
        r.t0_price ? (r.t0_price * (1 + (r.predicted_downside_pct || 0))).toFixed(2) : 'N/A',
        ((r.risk_probability || 0) * 100).toFixed(2)
      ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `screener_results_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className={`fade-in ${styles.page}`}>
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h1>Stock Screener</h1>
          <p>Find your next swing trade using ML predictions and fundamental filters.</p>
        </div>
        <div className={styles.presetButtons}>
          <div style={{display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap'}}>
            {savedPresets.map(p => (
              <div key={p.id} style={{display: 'flex', alignItems: 'center'}} className="btn btn-secondary">
                <span onClick={() => applyPreset(p.filters)} style={{cursor: 'pointer', paddingRight: '8px'}}>{p.name}</span>
                <Trash2 size={14} style={{cursor: 'pointer', opacity: 0.7}} onClick={() => deletePreset(p.id)} />
              </div>
            ))}
            <div style={{display: 'flex', alignItems: 'center', gap: '4px', marginLeft: '8px'}}>
              <input 
                type="text" 
                placeholder="New preset..." 
                className="input" 
                style={{padding: '4px 8px', width: '130px'}}
                value={newPresetName} 
                onChange={e => setNewPresetName(e.target.value)} 
              />
              <button className="btn btn-primary" style={{padding: '4px 8px'}} onClick={savePreset} disabled={!newPresetName || isSavingPreset}>Save</button>
            </div>
          </div>
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
                <label>Max Drawdown Potential (%)</label>
                <input 
                  type="number" 
                  className="input" 
                  value={filters.maxDrawdown} 
                  onChange={e => setFilters({...filters, maxDrawdown: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Min Reward/Risk Ratio</label>
                <input 
                  type="number" 
                  className="input" 
                  step="0.1"
                  value={filters.minRewardRisk} 
                  onChange={e => setFilters({...filters, minRewardRisk: e.target.value})} 
                />
              </div>

              <div className={styles.fieldGroup}>
                <label>Sector L2</label>
                <select 
                  className="input" 
                  value={filters.sectorL2} 
                  onChange={e => setFilters({...filters, sectorL2: e.target.value})}
                >
                  {sectorL2Options.map(s => (
                    <option key={s} value={s}>{s === 'all' ? 'All Sectors' : s}</option>
                  ))}
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label>Sector L3</label>
                <select 
                  className="input" 
                  value={filters.sectorL3} 
                  onChange={e => setFilters({...filters, sectorL3: e.target.value})}
                >
                  {sectorL3Options.map(s => (
                    <option key={s} value={s}>{s === 'all' ? 'All Sub-sectors' : s}</option>
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
            <div className={styles.resultsHeader} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2>{results.length} Results Found</h2>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setShowPercentage(!showPercentage)} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px' }}>
                  <ArrowUpDown size={16} /> {showPercentage ? 'Show Target Prices' : 'Show Percentages'}
                </button>
                <button className="btn btn-secondary" onClick={exportToCSV} disabled={results.length === 0 || loading} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px' }}>
                  <Save size={16} /> Export CSV
                </button>
              </div>
            </div>
            
            <div className={styles.tableWrapper}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th onClick={() => handleSort('nse_symbol')} className={styles.sortable}>
                      Symbol {filters.sortBy === 'nse_symbol' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('sector_l2')} className={styles.sortable}>
                      Sector L2 {filters.sortBy === 'sector_l2' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('sector_l3')} className={styles.sortable}>
                      Sector L3 {filters.sortBy === 'sector_l3' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('current_price')} className={styles.sortable}>
                      Current Price {filters.sortBy === 'current_price' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('t0_price')} className={styles.sortable}>
                      T0 Price {filters.sortBy === 't0_price' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('predicted_avg_pct')} className={styles.sortable}>
                      Avg Target {filters.sortBy === 'predicted_avg_pct' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('predicted_upside_pct')} className={styles.sortable}>
                      Upside {filters.sortBy === 'predicted_upside_pct' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('predicted_downside_pct')} className={styles.sortable}>
                      Downside {filters.sortBy === 'predicted_downside_pct' && <ArrowUpDown size={12} />}
                    </th>
                    <th onClick={() => handleSort('risk_probability')} className={styles.sortable}>
                      Risk Prob {filters.sortBy === 'risk_probability' && <ArrowUpDown size={12} />}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={9} className={styles.loadingCell}>
                        <Loader2 size={24} className="spinner text-blue" />
                      </td>
                    </tr>
                  ) : results.length === 0 ? (
                    <tr>
                      <td colSpan={9} className={styles.emptyCell}>
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
                        <td className="text-secondary" style={{maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
                          {r.sector_l2 || 'N/A'}
                        </td>
                        <td className="text-secondary" style={{maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
                          {r.sector_l3 || 'N/A'}
                        </td>
                        <td className="mono">₹{r.current_price?.toFixed(1) || 'N/A'}</td>
                        <td className="mono">₹{r.t0_price?.toFixed(1) || 'N/A'}</td>
                        <td className={`mono ${(r.predicted_avg_pct || 0) >= 0 ? 'text-green' : 'text-red'}`}>
                          {showPercentage 
                            ? `${((r.predicted_avg_pct || 0) * 100).toFixed(1)}%` 
                            : `₹${(r.t0_price * (1 + (r.predicted_avg_pct || 0))).toFixed(1)}`}
                        </td>
                        <td className="text-green mono">
                          {showPercentage 
                            ? `${((r.predicted_upside_pct || 0) * 100).toFixed(1)}%` 
                            : `₹${(r.t0_price * (1 + (r.predicted_upside_pct || 0))).toFixed(1)}`}
                        </td>
                        <td className="text-red mono">
                          {showPercentage 
                            ? `${((r.predicted_downside_pct || 0) * 100).toFixed(1)}%` 
                            : `₹${(r.t0_price * (1 + (r.predicted_downside_pct || 0))).toFixed(1)}`}
                        </td>
                        <td className="mono">{((r.risk_probability || 0) * 100).toFixed(1)}%</td>
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
