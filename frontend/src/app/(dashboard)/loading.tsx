'use client';

import { Loader2 } from 'lucide-react';

export default function DashboardLoading() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '80vh',
      gap: '16px'
    }}>
      <Loader2 size={40} className="spinner text-blue" />
      <p style={{ color: 'var(--text-secondary)' }}>Loading Dashboard...</p>
    </div>
  );
}
