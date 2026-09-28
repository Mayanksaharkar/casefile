import React, { useState, useMemo } from 'react';
import SeverityBadge from './SeverityBadge';
import IssueCard from './IssueCard';

export default function FindingsTable({ issues, auditId, repoPath }) {
  const [filterSev, setFilterSev] = useState('all');
  const [filterCat, setFilterCat] = useState('all');
  const [expandedId, setExpandedId] = useState(null);

  const categories = useMemo(() => Array.from(new Set(issues.map(i => i.category || 'functional'))), [issues]);

  const filtered = issues.filter(i => {
    if (filterSev !== 'all' && i.severity !== filterSev) return false;
    const cat = i.category || 'functional';
    if (filterCat !== 'all' && cat !== filterCat) return false;
    return true;
  });
  
  // Sort by confidence (needs human review queue)
  filtered.sort((a, b) => (b.confidence_score || 0) - (a.confidence_score || 0));

  async function handleTriage(issueId, decision) {
    try {
      await fetch(`/api/audits/${auditId}/findings/${issueId}/labels`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision })
      });
      // Naive optimism update - force reload to see DB changes is better, 
      // but for UX we just alert for now.
      alert(`Label saved: ${decision}`);
      window.location.reload();
    } catch (e) {
      alert('Failed to save label');
    }
  }

  function renderScore(score) {
    if (score === undefined || score === null) return <span style={{color: '#888'}}>N/A</span>;
    const pct = Math.round(score * 100);
    let color = pct > 80 ? '#10b981' : pct > 50 ? '#f59e0b' : '#ef4444';
    return <strong style={{ color }}>{pct}%</strong>;
  }

  function renderResolution(res) {
    if (!res) return null;
    const colors = { 'new': '#3b82f6', 'recurring': '#f59e0b', 'fixed': '#10b981', 'regression': '#ef4444' };
    return <span style={{ background: colors[res] || '#555', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem', color: '#fff', marginLeft: '8px' }}>{res.toUpperCase()}</span>;
  }

  return (
    <div className="findings-triage">
      <div className="triage-filters" style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', alignItems: 'center' }}>
        <strong>Filter by:</strong>
        <select value={filterSev} onChange={(e) => setFilterSev(e.target.value)} style={{ padding: '0.4rem', borderRadius: '4px', background: '#333', color: '#fff', border: '1px solid #444' }}>
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select value={filterCat} onChange={(e) => setFilterCat(e.target.value)} style={{ padding: '0.4rem', borderRadius: '4px', background: '#333', color: '#fff', border: '1px solid #444' }}>
          <option value="all">All Categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <span>{filtered.length} findings (Sorted by Confidence)</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', background: '#1e1e1e', borderRadius: '8px', overflow: 'hidden' }}>
          <thead>
            <tr style={{ background: '#2c2c2c', borderBottom: '1px solid #444' }}>
              <th style={{ padding: '12px' }}>Severity</th>
              <th style={{ padding: '12px' }}>Confidence</th>
              <th style={{ padding: '12px' }}>Category</th>
              <th style={{ padding: '12px' }}>Title & Status</th>
              <th style={{ padding: '12px' }}>Triage</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan="5" style={{ padding: '1rem', textAlign: 'center' }}>No findings match criteria.</td></tr>
            ) : filtered.map(issue => (
              <React.Fragment key={issue.id}>
                <tr style={{ borderBottom: '1px solid #333', background: issue.status === 'confirmed' ? '#1a2e1a' : issue.status === 'false-positive' ? '#2e1a1a' : 'transparent' }}>
                  <td style={{ padding: '12px' }}><SeverityBadge severity={issue.severity} /></td>
                  <td style={{ padding: '12px' }}>{renderScore(issue.confidence_score)}</td>
                  <td style={{ padding: '12px', textTransform: 'capitalize' }}>{issue.category || 'Functional'}</td>
                  <td style={{ padding: '12px' }}>
                    <div style={{ fontWeight: 'bold' }}>
                      {issue.title} {renderResolution(issue.resolution)}
                    </div>
                    <div style={{ fontFamily: 'monospace', color: '#aaa', fontSize: '0.85rem', marginTop: '4px' }}>{issue.route || 'N/A'}</div>
                  </td>
                  <td style={{ padding: '12px' }}>
                    <div style={{ display: 'flex', gap: '4px', marginBottom: '4px' }}>
                      <button onClick={() => handleTriage(issue.id, 'confirm')} style={{ background: '#10b981', color: '#fff', border: 'none', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>✓ Confirm</button>
                      <button onClick={() => handleTriage(issue.id, 'false-positive')} style={{ background: '#ef4444', color: '#fff', border: 'none', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>✗ False Pos</button>
                    </div>
                    <button 
                      onClick={() => setExpandedId(expandedId === issue.id ? null : issue.id)}
                      style={{ padding: '4px 8px', background: '#444', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem', width: '100%' }}>
                      {expandedId === issue.id ? 'Hide Details' : 'View Details'}
                    </button>
                  </td>
                </tr>
                {expandedId === issue.id && (
                  <tr style={{ background: '#111' }}>
                    <td colSpan="5" style={{ padding: '1rem' }}>
                      <IssueCard issue={issue} auditId={auditId} repoPath={repoPath} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
