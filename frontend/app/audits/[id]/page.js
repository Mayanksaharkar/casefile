'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getAudit, auditStreamUrl, reportUrl, startAudit, stopAudit } from '../../../lib/api';
import LiveView from '../../../components/LiveView';
import ProgressPanel from '../../../components/ProgressPanel';
import IssueCard from '../../../components/IssueCard';
import RegressionSummary from '../../../components/RegressionSummary';
import FindingsTable from '../../../components/FindingsTable';
import HitlInputCard from '../../../components/HitlInputCard';

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'];

export default function AuditReportPage({ params }) {
  const { id } = params;
  const router = useRouter();
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const [blocker, setBlocker] = useState(null);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const source = new EventSource(auditStreamUrl(id));
    let pollInterval = null;

    // Once an audit reaches a terminal state, nothing will ever change
    // again - keeping the stream open and polling every 8s forever would
    // just leak an idle connection and waste requests for as long as the
    // tab stays open.
    function stopLiveUpdates() {
      source.close();
      if (pollInterval) clearInterval(pollInterval);
    }

    source.addEventListener('state', (event) => {
      if (cancelled) return;
      try {
        const data = JSON.parse(event.data);
        setAudit(data);
        setError(null);
        setConnected(true);
        // Clear blocker when run resumes
        if (data.status !== 'blocked') setBlocker(null);
        if (data.status !== 'running' && data.status !== 'blocked') stopLiveUpdates();
      } catch (err) {
        // Ignore a malformed frame - the next one will correct the view.
      }
    });

    source.addEventListener('needs_input', (event) => {
      if (cancelled) return;
      try {
        const data = JSON.parse(event.data);
        setBlocker(data);
      } catch (err) {
        // ignore malformed frame
      }
    });

    source.onopen = () => {
      if (!cancelled) setConnected(true);
    };

    source.onerror = () => {
      // EventSource retries on its own; surface a "reconnecting" state
      // rather than an error banner while it does.
      if (!cancelled) setConnected(false);
    };

    // Safety net: if the live stream stalls behind a proxy/firewall,
    // this keeps the view eventually-correct every few seconds.
    pollInterval = setInterval(async () => {
      try {
        const data = await getAudit(id);
        if (cancelled) return;
        setAudit(data);
        if (data.status !== 'running' && data.status !== 'blocked') stopLiveUpdates();
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }, 8000);

    return () => {
      cancelled = true;
      stopLiveUpdates();
    };
  }, [id]);

  if (error && !audit) {
    return <div className="error-banner">{error}</div>;
  }

  if (!audit) {
    return <p className="subtitle">Loading audit…</p>;
  }

  const issuesBySeverity = SEVERITY_ORDER.reduce((acc, sev) => {
    acc[sev] = audit.issues.filter((i) => i.severity === sev);
    return acc;
  }, {});

  async function handleRerun() {
    try {
      const { id: newId } = await startAudit({
        targetUrl: audit.targetUrl,
        repoPath: audit.repoPath,
        budget: audit.budget,
        maxPages: audit.maxPages || 15,
        safeMode: audit.safeMode,
        compareAgainstId: audit.id,
      });
      router.push(`/audits/${newId}`);
    } catch (err) {
      alert('Failed to rerun audit: ' + err.message);
    }
  }

  async function handleStop() {
    if (!confirm('Are you sure you want to stop this audit?')) return;
    setStopping(true);
    try {
      await stopAudit(audit.id);
    } catch (err) {
      alert('Failed to stop audit: ' + err.message);
      setStopping(false);
    }
  }

  const isActive = audit.status === 'running' || audit.status === 'blocked';

  return (
    <>
      <div className="report-header">
        <div>
          <h2 className="eyebrow-free-title">{audit.targetUrl}</h2>
          <p className="subtitle" style={{ marginBottom: 0 }}>
            Started {new Date(audit.startedAt).toLocaleString()}
            {audit.completedAt ? ` · completed ${new Date(audit.completedAt).toLocaleString()}` : ''}
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span className={`status-pill ${audit.status}`}>{audit.status}</span>
          
          {isActive && (
            <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem' }}>
              <button 
                onClick={handleStop} 
                disabled={stopping}
                className="btn-secondary" 
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.875rem', borderColor: '#ef4444', color: '#ef4444' }}
              >
                {stopping ? 'Stopping...' : '⏹ Stop Audit'}
              </button>
            </div>
          )}

          {!isActive && (
            <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem' }}>
              <a href={reportUrl(audit.id)} target="_blank" rel="noreferrer">
                Open standalone HTML report ↗
              </a>
              <button onClick={handleRerun} className="btn-secondary" style={{ padding: '0.25rem 0.5rem', fontSize: '0.875rem' }}>
                ↻ Rerun Audit
              </button>
            </div>
          )}
        </div>
      </div>

      {audit.status === 'failed' && <div className="error-banner">Audit failed: {audit.error}</div>}

      <div className="summary-strip">
        <div className="stat">
          <b>{audit.progress.pagesDiscovered}</b>
          <span>pages</span>
        </div>
        <div className="stat">
          <b>{audit.progress.actionsExecuted}</b>
          <span>actions</span>
        </div>
        <div className="stat">
          <b>{audit.summary.total}</b>
          <span>issues</span>
        </div>
        {SEVERITY_ORDER.map((sev) => (
          <div className="stat" key={sev}>
            <b>{audit.summary[sev]}</b>
            <span>{sev}</span>
          </div>
        ))}
      </div>

      {isActive && (
        <>
          <LiveView audit={audit} connected={connected} />
          <ProgressPanel audit={audit} />
        </>
      )}

      {blocker && (
        <HitlInputCard
          blocker={blocker}
          onResolved={() => setBlocker(null)}
        />
      )}

      {audit.configSummary && audit.configSummary.found && (
        <p className="hint" style={{ marginBottom: '1.5rem' }}>
          Using business rules contract from {audit.repoPath}
          {audit.configSummary.hasFlows ? ' (flows.yaml found)' : ''}
          {audit.configSummary.hasRules ? ' (rules.yaml found)' : ''}.
        </p>
      )}

      <RegressionSummary regression={audit.regression} />

      {!isActive && audit.summary.total === 0 && (
        <div className="empty-state">No issues found in this run.</div>
      )}

      {audit.summary.total > 0 && (
        <section className="triage-section" style={{ marginTop: '2rem' }}>
          <h2>Findings Triage</h2>
          <FindingsTable issues={audit.issues} auditId={audit.id} repoPath={audit.repoPath} />
        </section>
      )}
    </>
  );
}
