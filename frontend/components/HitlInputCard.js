'use client';

import { useState } from 'react';
import { API_BASE } from '../lib/api';

/**
 * Renders an "Auditor needs input" card inline in the audit live-feed.
 * Receives a `blocker` object:
 *   { runId, question, fieldType, screenshotPath }
 * `onResolved` is called after a successful resume so the parent can hide the card.
 */
export default function HitlInputCard({ blocker, onResolved }) {
  const [value, setValue] = useState('');
  const [saveAsFixture, setSaveAsFixture] = useState(false);
  const [fixtureType, setFixtureType] = useState('ephemeral');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!blocker) return null;

  const { runId, question, fieldType, screenshotPath } = blocker;

  const screenshotUrl = screenshotPath
    ? `${API_BASE}/data/audits/${runId}/${screenshotPath}`
    : null;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!value.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/hitl/${runId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          value: value.trim(),
          save_as_fixture: saveAsFixture,
          fixture_vault_type: fixtureType,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Request failed (${res.status})`);
      }
      onResolved && onResolved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function renderInput() {
    const base = {
      value,
      onChange: e => setValue(e.target.value),
      disabled: submitting,
      style: { width: '100%', marginBottom: '0.75rem' },
    };

    if (fieldType === 'otp' || fieldType === 'email') {
      return <input type={fieldType === 'otp' ? 'text' : 'email'} placeholder={fieldType === 'otp' ? 'Enter OTP / code' : 'Enter email'} {...base} />;
    }
    if (fieldType === 'select') {
      return <input type="text" placeholder="Enter the value to select" {...base} />;
    }
    if (fieldType === 'password') {
      return <input type="password" placeholder="Enter password" {...base} />;
    }
    return <input type="text" placeholder="Enter value…" {...base} />;
  }

  return (
    <div className="hitl-card">
      <div className="hitl-card-header">
        <span className="hitl-badge">⏸ Auditor Needs Input</span>
      </div>

      {screenshotUrl && (
        <div className="hitl-screenshot-wrap">
          <img src={screenshotUrl} alt="Current page where agent is blocked" className="hitl-screenshot" />
        </div>
      )}

      <p className="hitl-question">{question}</p>

      <form onSubmit={handleSubmit}>
        {renderInput()}

        <div className="hitl-fixture-row">
          <label className="hitl-fixture-label">
            <input
              type="checkbox"
              checked={saveAsFixture}
              onChange={e => setSaveAsFixture(e.target.checked)}
              disabled={submitting}
            />
            <span>Remember this answer for future runs</span>
          </label>
          {saveAsFixture && (
            <select
              value={fixtureType}
              onChange={e => setFixtureType(e.target.value)}
              disabled={submitting}
              className="hitl-vault-type-select"
            >
              <option value="ephemeral">Ephemeral (ask again next time)</option>
              <option value="static">Static (auto-fill next time)</option>
            </select>
          )}
        </div>

        {error && <div className="hitl-error">{error}</div>}

        <button type="submit" disabled={submitting || !value.trim()} className="hitl-submit-btn">
          {submitting ? 'Submitting…' : 'Submit & Resume'}
        </button>
      </form>
    </div>
  );
}
