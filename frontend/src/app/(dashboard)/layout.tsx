import Sidebar from '@/components/Layout/Sidebar';
import Header from '@/components/Layout/Header';
import styles from './dashboard-layout.module.css';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.layout}>
      <Sidebar />
      <Header />
      <main className={styles.main}>
        {children}
      </main>
    </div>
  );
}
