'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { 
  TrendingUp, TrendingDown, Info, Calendar, DollarSign, 
  Percent, ShieldAlert, Loader2, Target, Star, Check, Plus, ChevronDown
} from 'lucide-react';
import styles from './stock.module.css';

// Dynamically import chart with SSR disabled because it uses canvas/window
const CandlestickChart = dynamic(
  () => import('@/components/Charts/CandlestickChart'),
  { ssr: false, loading: () => <div className={styles.chartLoader}><Loader2 className="spinner" size={32} /></div> }
);

interface StockData {
  ohlcv: any[];
  prediction: any;
  fundamentals: any;
}

function formatPct(val: number): string {
  if (val === undefined || val === null) return 'N/A';
  return `${(val * 100).toFixed(1)}%`;
}

function formatInr(val: number): string {
  if (val === undefined || val === null) return 'N/A';
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`;
}

export default function StockDetailPage() {
  const params = useParams();
  const symbol = params.symbol as string;
  const [data, setData] = useState<StockData | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Multi-watchlist state
  const [watchlists, setWatchlists] = useState<{id: string, name: string, hasStock: boolean}[]>([]);
  const [wlLoading, setWlLoading] = useState(true);
  const [wlDropdownOpen, setWlDropdownOpen] = useState(false);

  useEffect(() => {
    async function fetchData() {
      try {
        // Fetch stock data
        const res = await fetch(`/api/stocks/${symbol}`);
        if (res.ok) setData(await res.json());
      } catch (err) {
        console.error('Failed to fetch data:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [symbol]);

  useEffect(() => {
    async function fetchWatchlistStatus() {
      try {
        const metaRes = await fetch('/api/watchlists');
        if (!metaRes.ok) return;
        const metaData = await metaRes.json();
        
        // For each watchlist, check if stock is in it
        // Note: For a scalable app, you'd want an API endpoint that returns which watchlists contain the stock in one call.
        // For now, we'll fetch items for each list.
        const enriched = await Promise.all(metaData.watchlists.map(async (wl: any) => {
          const itemsRes = await fetch(`/api/watchlists/${wl.id}/items`);
          let hasStock = false;
          if (itemsRes.ok) {
            const itemsData = await itemsRes.json();
            hasStock = itemsData.results?.some((i: any) => i.nse_symbol === symbol);
          }
          return { id: wl.id, name: wl.name, hasStock };
        }));
        
        setWatchlists(enriched);
      } catch (err) {
        console.error('Failed to fetch watchlists', err);
      } finally {
        setWlLoading(false);
      }
    }
    fetchWatchlistStatus();
  }, [symbol]);

  const toggleWatchlistItem = async (wlId: string, hasStock: boolean) => {
    setWatchlists(prev => prev.map(w => w.id === wlId ? { ...w, hasStock: !hasStock } : w));
    
    try {
      let res;
      if (hasStock) {
        res = await fetch(`/api/watchlists/${wlId}/items`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol })
        });
      } else {
        res = await fetch(`/api/watchlists/${wlId}/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol })
        });
      }
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    } catch (err) {
      console.error(err);
      // revert on error
      setWatchlists(prev => prev.map(w => w.id === wlId ? { ...w, hasStock } : w));
    }
  };

  if (loading) {
    return (
      <div className={styles.pageLoader}>
        <Loader2 className="spinner text-blue" size={40} />
        <p>Loading {symbol} data...</p>
      </div>
    );
  }

  if (!data || data.ohlcv.length === 0) {
    return (
      <div className={styles.errorState}>
        <ShieldAlert size={48} className="text-red" />
        <h2>Stock Not Found</h2>
        <p>We couldn't find data for {symbol}. It might not be in our covered universe.</p>
      </div>
    );
  }

  const { ohlcv, prediction, fundamentals } = data;
  const latestPrice = ohlcv[ohlcv.length - 1].close;
  const isRisky = prediction?.risk_flag_balanced_0_50 === 1;

  return (
    <div className={`fade-in ${styles.page}`}>
      {/* Header Section */}
      <div className={styles.headerRow}>
        <div className={styles.titleSection}>
          <h1>{symbol}</h1>
          <div className={styles.badges}>
            <span className="badge badge-blue">{fundamentals?.sector_classification?.split(' > ').pop() || 'Unknown Sector'}</span>
            {prediction && (
              <span className={`badge ${isRisky ? 'badge-red' : 'badge-green'}`}>
                {isRisky ? 'High Risk' : 'Balanced Risk'}
              </span>
            )}
            
            <div style={{ position: 'relative', marginLeft: 'auto' }}>
              <button 
                className={`btn ${watchlists.some(w => w.hasStock) ? 'btn-secondary' : 'btn-primary'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                onClick={() => setWlDropdownOpen(!wlDropdownOpen)}
                disabled={wlLoading}
              >
                {wlLoading ? <Loader2 size={16} className="spinner" /> : <Star size={16} />}
                Watchlist
                <ChevronDown size={14} />
              </button>
              
              {wlDropdownOpen && (
                <div className={styles.wlDropdown}>
                  {watchlists.length === 0 ? (
                    <div style={{ padding: '8px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      No watchlists found.
                    </div>
                  ) : (
                    watchlists.map(wl => (
                      <button 
                        key={wl.id} 
                        className={styles.wlItem}
                        onClick={() => toggleWatchlistItem(wl.id, wl.hasStock)}
                      >
                        <span>{wl.name}</span>
                        {wl.hasStock ? <Check size={14} className="text-green" /> : <Plus size={14} className="text-secondary" />}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
        
        <div className={styles.priceSection}>
          <div className={styles.mainPrice}>{formatInr(latestPrice)}</div>
          {prediction && (
            <div className={styles.t0Price}>
              T0 Price: {formatInr(prediction.price_on_t0_inr)}
            </div>
          )}
        </div>
      </div>

      <div className={styles.grid}>
        {/* Main Chart Column */}
        <div className={styles.chartCol}>
          <div className={`card ${styles.chartCard}`}>
            <div className={styles.cardHeader}>
              <h3><Target size={18} /> Technical & Prediction Chart</h3>
              <div className={styles.legend}>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{background: 'var(--accent-green)'}}></span>Max Upside</span>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{background: 'var(--accent-purple)'}}></span>Avg Target</span>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{background: 'var(--accent-red)'}}></span>Max Drawdown</span>
              </div>
            </div>
            <div className={styles.chartWrapper}>
              <CandlestickChart data={ohlcv} prediction={prediction} />
            </div>
          </div>
          
          {/* Description */}
          {fundamentals?.company_description && (
            <div className={`card ${styles.descCard}`}>
              <h3><Info size={18} /> About Company</h3>
              <p>{fundamentals.company_description}</p>
            </div>
          )}
        </div>

        {/* Sidebar Column */}
        <div className={styles.sideCol}>
          {/* Prediction Card */}
          {prediction && (
            <div className={`card ${styles.predCard}`}>
              <h3>Model Forecast</h3>
              <p className={styles.predDate}>
                <Calendar size={14} /> Predicted on {prediction.prediction_date}
              </p>
              
              <div className={styles.predGrid}>
                <div className={styles.predItem}>
                  <p className={styles.predLabel}>Max Upside</p>
                  <p className="text-green mono" style={{ fontSize: '1.2rem', fontWeight: 700 }}>
                    <TrendingUp size={16} /> {formatInr(prediction.predicted_upside_inr)}
                  </p>
                </div>
                <div className={styles.predItem}>
                  <p className={styles.predLabel}>Max Drawdown</p>
                  <p className="text-red mono" style={{ fontSize: '1.2rem', fontWeight: 700 }}>
                    <TrendingDown size={16} /> {formatInr(prediction.predicted_downside_inr)}
                  </p>
                </div>
                <div className={styles.predItem}>
                  <p className={styles.predLabel}>Average Target</p>
                  <p className="text-purple mono" style={{ fontSize: '1.2rem', fontWeight: 700 }}>
                    <Target size={16} /> {formatInr(prediction.predicted_avg_inr)}
                  </p>
                </div>
                <div className={styles.predItem}>
                  <p className={styles.predLabel}>Risk Probability</p>
                  <p className="mono" style={{ fontSize: '1.2rem', fontWeight: 700 }}>
                    {formatPct(prediction.risk_probability)}
                  </p>
                </div>
              </div>

              {prediction.board_meeting_date && (
                <div className={styles.boardMeeting}>
                  <Calendar size={16} className="text-gold" />
                  <span>Last Board Meeting: <strong>{prediction.board_meeting_date}</strong></span>
                </div>
              )}
            </div>
          )}

          {/* Fundamentals Card */}
          {fundamentals && (
            <div className={`card ${styles.fundCard}`}>
              <h3>Fundamental Ratios</h3>
              <ul className={styles.ratioList}>
                <li>
                  <span className={styles.ratioLabel}>P/E Ratio</span>
                  <span className="mono">{fundamentals.pe_ratio || 'N/A'}</span>
                </li>
                <li>
                  <span className={styles.ratioLabel}>ROCE</span>
                  <span className="mono">{fundamentals.roce || 'N/A'}</span>
                </li>
                <li>
                  <span className={styles.ratioLabel}>ROE</span>
                  <span className="mono">{fundamentals.roe || 'N/A'}</span>
                </li>
                <li>
                  <span className={styles.ratioLabel}>Dividend Yield</span>
                  <span className="mono">{fundamentals.dividend_yield || 'N/A'}</span>
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
