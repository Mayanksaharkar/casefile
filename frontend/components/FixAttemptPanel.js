'use client';

import { useState } from 'react';
import { attemptFix } from '../lib/api';

export default function FixAttemptPanel({ auditId, issue, canFix }) {
  const [showForm, setShowForm] = useState(false);
  const [startCommand, setStartCommand] = useState('npm run dev');
  const [verifyPort, setVerifyPort] = useState(4310);
  const [autoPR, setAutoPR] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const attempt = issue.fixAttempt;
  const running = attempt && attempt.status === 'running';

  async function start() {
    setError(null);
    setStarting(true);
    try {
      await attemptFix(auditId, issue.id, { startCommand, verifyPort: Number(verifyPort), autoPR });
      setShowForm(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  if (!canFix) return null;

  return (
    <div style={{ marginTop: '1rem', borderTop: '1px solid var(--line)', paddingTop: '0.85rem' }}>
      {!attempt && !showForm && (
        <button type="button" className="copy-btn" onClick={() => setShowForm(true)}>
          Attempt fix
        </button>
      )}

      {showForm && (
        <div>
          {error && <div className="error-banner">{error}</div>}
          <div className="row">
            <div className="field">
              <label>Dev server start command</label>
              <input type="text" value={startCommand} onChange={(e) => setStartCommand(e.target.value)} />
            </div>
            <div className="field">
              <label>Verification port</label>
              <input type="number" value={verifyPort} onChange={(e) => setVerifyPort(e.target.value)} />
            </div>
          </div>
          <div className="field checkbox-field">
            <input id={`autoPR-${issue.id}`} type="checkbox" checked={autoPR} onChange={(e) => setAutoPR(e.target.checked)} />
            <label htmlFor={`autoPR-${issue.id}`} style={{ marginBottom: 0 }}>
              Auto-open a PR once the fix is verified
              <span className="hint" style={{ marginTop: '0.15rem' }}>
                Off by default: a verified fix is committed on a local branch for you to push yourself. On: pushes
                and opens a GitHub PR automatically (requires <code>GITHUB_TOKEN</code>). Either way, nothing is
                ever auto-merged.
              </span>
            </label>
          </div>
          <button type="button" className="submit-btn" onClick={start} disabled={starting}>
            {starting ? 'Starting…' : 'Start fix attempt'}
          </button>{' '}
          <button type="button" className="copy-btn" onClick={() => setShowForm(false)}>
            Cancel
          </button>
        </div>
      )}

      {attempt && !showForm && (
        <div>
          <div className="issue-card-head" style={{ marginBottom: '0.5rem' }}>
            <span className={`status-pill ${attempt.status}`}>{running ? 'fixing' : attempt.status}</span>
            {attempt.branch && <span className="mono">{attempt.branch}</span>}
            {typeof attempt.attempts === 'number' && attempt.attempts > 0 && <span>attempt {attempt.attempts}/2</span>}
          </div>

          {attempt.prUrl && (
            <p>
              <a href={attempt.prUrl} target="_blank" rel="noreferrer">
                Open pull request ↗
              </a>
            </p>
          )}
          {attempt.status === 'succeeded' && !attempt.prUrl && attempt.branch && (
            <p className="hint">
              Verified and committed on <code>{attempt.branch}</code> - push it and open a PR when you're ready.
            </p>
          )}
          {attempt.status === 'failed' && attempt.worktreeDir && (
            <p className="hint">
              Left for manual review at <code>{attempt.worktreeDir}</code> on branch <code>{attempt.branch}</code>.
            </p>
          )}

          {attempt.log && attempt.log.length > 0 && (
            <div className="progress-log" style={{ marginTop: '0.5rem' }}>
              {attempt.log
                .slice(-20)
                .slice()
                .reverse()
                .map((entry, i) => (
                  <div key={i}>
                    {new Date(entry.at).toLocaleTimeString()} — {entry.message}
                  </div>
                ))}
            </div>
          )}

          {!running && (
            <button type="button" className="copy-btn" style={{ marginTop: '0.5rem' }} onClick={() => setShowForm(true)}>
              Attempt again
            </button>
          )}
        </div>
      )}
    </div>
  );
}
