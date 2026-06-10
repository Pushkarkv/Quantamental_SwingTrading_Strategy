'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Star, Loader2, ArrowUpRight, ArrowDownRight, Trash2, Plus, Edit2, List, Save, X } from 'lucide-react';
import styles from './watchlist.module.css';

interface WatchlistMeta {
  id: string;
  name: string;
  created_at: string;
}

interface WatchlistItem {
  nse_symbol: string;
  stock_name: string;
  current_price: number;
  predicted_upside_pct: number;
  predicted_downside_pct: number;
  predicted_avg_pct: number;
  risk_probability: number;
  risk_flag_balanced_0_50: number;
  added_at: string;
}

function formatPct(val: number): string {
  if (val === null || val === undefined) return 'N/A';
  return `${(val * 100).toFixed(1)}%`;
}

function formatInr(val: number): string {
  if (val === null || val === undefined) return 'N/A';
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`;
}

export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<WatchlistMeta[]>([]);
  const [selectedListId, setSelectedListId] = useState<string | null>(null);
  const [items, setItems] = useState<WatchlistItem[]>([]);
  
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  
  // Create / Rename State
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  const fetchWatchlists = async () => {
    try {
      const res = await fetch('/api/watchlists');
      if (res.ok) {
        const data = await res.json();
        setWatchlists(data.watchlists || []);
        if (data.watchlists.length > 0 && !selectedListId) {
          setSelectedListId(data.watchlists[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch watchlists:', err);
    } finally {
      setLoadingMeta(false);
    }
  };

  const fetchItems = async (listId: string) => {
    setLoadingItems(true);
    try {
      const res = await fetch(`/api/watchlists/${listId}/items`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.results || []);
      }
    } catch (err) {
      console.error('Failed to fetch items:', err);
    } finally {
      setLoadingItems(false);
    }
  };

  useEffect(() => {
    fetchWatchlists();
  }, []);

  useEffect(() => {
    if (selectedListId) {
      fetchItems(selectedListId);
    } else {
      setItems([]);
    }
  }, [selectedListId]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const res = await fetch('/api/watchlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() })
      });
      if (res.ok) {
        const data = await res.json();
        const newList = { id: data.id, name: data.name, created_at: new Date().toISOString() };
        setWatchlists([...watchlists, newList]);
        setSelectedListId(newList.id);
        setIsCreating(false);
        setNewName('');
      }
    } catch (err) {
      console.error('Failed to create:', err);
    }
  };

  const handleRename = async (id: string) => {
    if (!editName.trim()) return;
    try {
      const res = await fetch(`/api/watchlists/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName.trim() })
      });
      if (res.ok) {
        setWatchlists(watchlists.map(w => w.id === id ? { ...w, name: editName.trim() } : w));
        setEditingId(null);
      }
    } catch (err) {
      console.error('Failed to rename:', err);
    }
  };

  const handleDeleteList = async (id: string) => {
    if (!confirm('Are you sure you want to delete this watchlist?')) return;
    try {
      const res = await fetch(`/api/watchlists/${id}`, { method: 'DELETE' });
      if (res.ok) {
        const updated = watchlists.filter(w => w.id !== id);
        setWatchlists(updated);
        if (selectedListId === id) {
          setSelectedListId(updated.length > 0 ? updated[0].id : null);
        }
      }
    } catch (err) {
      console.error('Failed to delete list:', err);
    }
  };

  const handleRemoveItem = async (symbol: string) => {
    if (!selectedListId) return;
    const old = [...items];
    setItems(items.filter(w => w.nse_symbol !== symbol));
    
    try {
      const res = await fetch(`/api/watchlists/${selectedListId}/items`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      if (!res.ok) throw new Error('Failed to delete');
    } catch (err) {
      console.error(err);
      setItems(old); // revert
    }
  };

  if (loadingMeta) {
    return (
      <div className={styles.loaderArea}>
        <Loader2 size={32} className="spinner text-blue" />
        <p>Loading watchlists...</p>
      </div>
    );
  }

  return (
    <div className={`fade-in ${styles.page}`}>
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h1><Star className="text-gold" size={28} /> Watchlists</h1>
          <p>Organize and monitor your favorite stocks.</p>
        </div>
      </div>

      <div className={styles.layout}>
        {/* Sidebar */}
        <div className={`card ${styles.sidebar}`}>
          <div className={styles.sidebarHeader}>
            <h3>My Lists</h3>
            {!isCreating && (
              <button className="btn btn-ghost" onClick={() => setIsCreating(true)} style={{padding: '4px'}}>
                <Plus size={16} />
              </button>
            )}
          </div>
          
          {isCreating && (
            <div className={styles.createBox}>
              <input 
                autoFocus
                type="text" 
                className="input" 
                placeholder="List name..." 
                value={newName} 
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreate()}
              />
              <div className={styles.createActions}>
                <button className="btn btn-primary" onClick={handleCreate} style={{padding: '4px 8px', fontSize: '0.7rem'}}>Save</button>
                <button className="btn btn-ghost" onClick={() => setIsCreating(false)} style={{padding: '4px 8px', fontSize: '0.7rem'}}>Cancel</button>
              </div>
            </div>
          )}

          <div className={styles.listContainer}>
            {watchlists.length === 0 && !isCreating && (
              <p className={styles.emptyText}>No watchlists created.</p>
            )}
            {watchlists.map(list => (
              <div 
                key={list.id} 
                className={`${styles.listItem} ${selectedListId === list.id ? styles.activeList : ''}`}
                onClick={() => { if (editingId !== list.id) setSelectedListId(list.id); }}
              >
                {editingId === list.id ? (
                  <div className={styles.editBox}>
                    <input 
                      autoFocus
                      type="text" 
                      className="input" 
                      value={editName}
                      onChange={e => setEditName(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleRename(list.id)}
                      onClick={e => e.stopPropagation()}
                    />
                    <button className="btn btn-ghost text-green" onClick={(e) => { e.stopPropagation(); handleRename(list.id); }}><Save size={14} /></button>
                    <button className="btn btn-ghost text-red" onClick={(e) => { e.stopPropagation(); setEditingId(null); }}><X size={14} /></button>
                  </div>
                ) : (
                  <>
                    <div className={styles.listName}>
                      <List size={14} className="text-secondary" />
                      <span>{list.name}</span>
                    </div>
                    {selectedListId === list.id && (
                      <div className={styles.listActions}>
                        <button className="btn btn-ghost" onClick={(e) => { e.stopPropagation(); setEditName(list.name); setEditingId(list.id); }}><Edit2 size={12} /></button>
                        <button className="btn btn-ghost text-red" onClick={(e) => { e.stopPropagation(); handleDeleteList(list.id); }}><Trash2 size={12} /></button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Main Content */}
        <div className={`card ${styles.mainContent}`}>
          {!selectedListId ? (
            <div className={styles.emptyState}>
              <Star size={48} className="text-muted" />
              <h2>No Watchlist Selected</h2>
              <p>Select a watchlist from the sidebar or create a new one.</p>
            </div>
          ) : loadingItems ? (
             <div className={styles.loaderArea}>
               <Loader2 size={32} className="spinner text-blue" />
             </div>
          ) : items.length === 0 ? (
            <div className={styles.emptyState}>
              <Star size={48} className="text-muted" />
              <h2>This watchlist is empty</h2>
              <p>Go to the screener or search for a stock to add it to your watchlist.</p>
              <Link href="/screener" className="btn btn-primary" style={{marginTop: '16px'}}>
                Go to Screener
              </Link>
            </div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Current Price</th>
                    <th>Predicted Avg Target</th>
                    <th>Max Upside</th>
                    <th>Max Drawdown</th>
                    <th>Risk Level</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => (
                    <tr key={item.nse_symbol}>
                      <td>
                        <Link href={`/stock/${item.nse_symbol}`} className={styles.symbolLink}>
                          <strong>{item.nse_symbol}</strong>
                          <span className={styles.stockName}>{item.stock_name}</span>
                        </Link>
                      </td>
                      <td className="mono">{formatInr(item.current_price)}</td>
                      <td className={`mono ${item.predicted_avg_pct >= 0 ? 'text-green' : 'text-red'}`}>
                        {item.predicted_avg_pct >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                        {formatPct(item.predicted_avg_pct)}
                      </td>
                      <td className="text-green mono">{formatPct(item.predicted_upside_pct)}</td>
                      <td className="text-red mono">{formatPct(item.predicted_downside_pct)}</td>
                      <td>
                        <span className={`badge ${item.risk_flag_balanced_0_50 === 1 ? 'badge-red' : 'badge-green'}`}>
                          {item.risk_flag_balanced_0_50 === 1 ? 'Risky' : 'Safe'}
                        </span>
                      </td>
                      <td>
                        <button 
                          className="btn btn-ghost" 
                          onClick={() => handleRemoveItem(item.nse_symbol)}
                          title="Remove from watchlist"
                          style={{color: 'var(--accent-red)', padding: '6px'}}
                        >
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
