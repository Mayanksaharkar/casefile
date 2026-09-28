'use client';

import { useState, useEffect } from 'react';

export default function EvalsPage() {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    fetch('/api/evals')
      .then(res => res.json())
      .then(data => setMetrics(data))
      .catch(err => console.error(err));
  }, []);

  if (!metrics) return <div style={{ padding: '2rem' }}>Loading metrics...</div>;

  return (
    <div className="evals-page" style={{ padding: '2rem' }}>
      <h1>Ongoing Eval Reporting</h1>
      <p style={{ color: '#aaa', marginBottom: '2rem' }}>Precision & Recall tracking to justify QA autonomous ownership.</p>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', textAlign: 'center' }}>
          <h2 style={{ color: '#aaa', fontSize: '1.2rem', marginBottom: '1rem' }}>Precision (Confirmed / Total Labeled)</h2>
          <div style={{ fontSize: '4rem', fontWeight: 'bold', color: metrics.precision_pct > 80 ? '#10b981' : '#f59e0b' }}>
            {metrics.precision_pct}%
          </div>
          <p style={{ marginTop: '1rem', color: '#888' }}>{metrics.confirmed} confirmed / {metrics.total_labeled} labeled findings</p>
        </div>

        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', textAlign: 'center' }}>
          <h2 style={{ color: '#aaa', fontSize: '1.2rem', marginBottom: '1rem' }}>Recall (Bugs Found / Known Bugs)</h2>
          <div style={{ fontSize: '4rem', fontWeight: 'bold', color: metrics.recall_pct > 80 ? '#10b981' : '#f59e0b' }}>
            {metrics.recall_pct}%
          </div>
          <p style={{ marginTop: '1rem', color: '#888' }}>Estimated against baseline seeded test sets</p>
        </div>
      </div>
      
      <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', marginTop: '2rem' }}>
        <h2>System Stats</h2>
        <ul style={{ color: '#aaa', lineHeight: '2' }}>
          <li>Total Findings Emitted: <b>{metrics.total_findings}</b></li>
          <li>False Positives Logged: <b>{metrics.false_positives}</b></li>
          <li>Cross-browser matrix: <b>Active (Desktop, Tablet, Mobile)</b></li>
          <li>Visual Regression: <b>Active (Pixelmatch enabled)</b></li>
        </ul>
      </div>
    </div>
  );
}
