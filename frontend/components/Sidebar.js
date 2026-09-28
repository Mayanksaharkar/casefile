'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { listAudits } from '../lib/api';

function timeAgo(iso) {
  if (!iso) return '';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function shortUrl(url) {
  try {
    const u = new URL(url);
    return u.host + (u.pathname !== '/' ? u.pathname : '');
  } catch (err) {
    return url;
  }
}

export default function Sidebar() {
  const [audits, setAudits] = useState([]);
  const pathname = usePathname();

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await listAudits();
        if (!cancelled) setAudits(data);
      } catch (err) {}
    }

    poll();
    const interval = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <aside className="sidebar">
      <Link href="/" className="brand">
        <h1>Casefile</h1>
        <p>adaptive web app auditor</p>
      </Link>

      <Link href="/" className="new-audit-btn">
        New audit
      </Link>

      <Link href="/guide" style={{ 
        display: 'block', 
        padding: '0.75rem 1rem', 
        marginBottom: '1rem', 
        fontSize: '0.9rem', 
        color: 'var(--text-secondary)',
        textDecoration: 'none',
        border: '1px solid var(--border)',
        borderRadius: '6px'
      }}>
        📖 Usage Guide
      </Link>

      <Link href="/requirements" style={{ 
        display: 'block', 
        padding: '0.75rem 1rem', 
        marginBottom: '1rem', 
        fontSize: '0.9rem', 
        color: 'var(--text-secondary)',
        textDecoration: 'none',
        border: '1px solid var(--border)',
        borderRadius: '6px'
      }}>
        📋 Test Plans
      </Link>

      <Link href="/config" style={{ 
        display: 'block', 
        padding: '0.75rem 1rem', 
        marginBottom: '1rem', 
        fontSize: '0.9rem', 
        color: 'var(--text-secondary)',
        textDecoration: 'none',
        border: '1px solid var(--border)',
        borderRadius: '6px'
      }}>
        ⚙️ Settings
      </Link>

      <Link href="/evals" style={{ 
        display: 'block', 
        padding: '0.75rem 1rem', 
        marginBottom: '1rem', 
        fontSize: '0.9rem', 
        color: 'var(--text-secondary)',
        textDecoration: 'none',
        border: '1px solid var(--border)',
        borderRadius: '6px'
      }}>
        📊 Eval Reporting
      </Link>

      <div className="sidebar-list">
        {audits.length === 0 && <p className="hint">No audits yet.</p>}
        {audits.map((a) => (
          <Link
            key={a.id}
            href={`/audits/${a.id}`}
            className={`sidebar-item${pathname === `/audits/${a.id}` ? ' active' : ''}`}
          >
            <span className="url">{shortUrl(a.targetUrl)}</span>
            <span className="meta">
              <span>{a.status}</span>
              <span>&middot;</span>
              <span>{a.summary ? a.summary.total : 0} issue(s)</span>
              <span>&middot;</span>
              <span>{timeAgo(a.startedAt)}</span>
            </span>
          </Link>
        ))}
      </div>
    </aside>
  );
}
