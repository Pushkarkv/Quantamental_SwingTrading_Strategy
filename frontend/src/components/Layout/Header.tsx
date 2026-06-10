'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { signOut } from 'next-auth/react';
import { Sun, Moon, Search, LogOut, User, Loader2 } from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';
import styles from './Header.module.css';

interface Suggestion {
  nse_symbol: string;
  company_name: string;
}

export default function Header() {
  const { theme, toggleTheme } = useTheme();
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const router = useRouter();
  const searchContainerRef = useRef<HTMLDivElement>(null);

  // Handle click outside to close dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced search fetch
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (searchQuery.trim().length >= 2) {
        setIsSearching(true);
        try {
          const res = await fetch(`/api/search?q=${encodeURIComponent(searchQuery)}`);
          if (res.ok) {
            const data = await res.json();
            setSuggestions(data.results || []);
            setShowDropdown(true);
          }
        } catch (error) {
          console.error('Failed to fetch search suggestions', error);
        } finally {
          setIsSearching(false);
        }
      } else {
        setSuggestions([]);
        setShowDropdown(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/stock/${searchQuery.trim().toUpperCase()}`);
      setSearchQuery('');
      setShowDropdown(false);
    }
  };

  const handleSelectSuggestion = (symbol: string) => {
    router.push(`/stock/${symbol}`);
    setSearchQuery('');
    setShowDropdown(false);
  };

  return (
    <header className={styles.header}>
      <div className={styles.searchContainer} ref={searchContainerRef}>
        <form className={styles.searchBar} onSubmit={handleSearch}>
          {isSearching ? (
            <Loader2 size={16} className={`${styles.searchIcon} spinner`} />
          ) : (
            <Search size={16} className={styles.searchIcon} />
          )}
          <input
            type="text"
            placeholder="Search stock symbol or name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => { if (suggestions.length > 0) setShowDropdown(true); }}
            className={styles.searchInput}
            id="global-stock-search"
            autoComplete="off"
          />
        </form>

        {showDropdown && suggestions.length > 0 && (
          <div className={styles.searchDropdown}>
            {suggestions.map((item) => (
              <button
                key={item.nse_symbol}
                className={styles.suggestionItem}
                onClick={() => handleSelectSuggestion(item.nse_symbol)}
                type="button"
              >
                <span className={styles.suggestionSymbol}>{item.nse_symbol}</span>
                <span className={styles.suggestionName}>{item.company_name}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className={styles.actions}>
        <button
          className={styles.themeToggle}
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          id="theme-toggle-btn"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        <div className={styles.userMenu}>
          <button className={styles.userAvatar} id="user-menu-btn">
            <User size={16} />
          </button>
          <button
            className={styles.logoutBtn}
            onClick={() => signOut({ callbackUrl: '/login' })}
            id="logout-btn"
          >
            <LogOut size={16} />
            <span>Logout</span>
          </button>
        </div>
      </div>
    </header>
  );
}
