'use client';

import { ShieldAlert } from 'lucide-react';
import { useEffect } from 'react';

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '80vh',
      gap: '16px',
      textAlign: 'center'
    }}>
      <ShieldAlert size={64} className="text-red" />
      <h2>Something went wrong!</h2>
      <p style={{ color: 'var(--text-secondary)' }}>
        An unexpected error occurred while loading this page.
      </p>
      <button
        onClick={() => reset()}
        className="btn btn-primary"
      >
        Try again
      </button>
    </div>
  );
}
