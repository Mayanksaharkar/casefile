'use client';

import { useState } from 'react';
import SeverityBadge, { COLORS } from './SeverityBadge';
import FixAttemptPanel from './FixAttemptPanel';
import { evidenceUrl } from '../lib/api';

export default function IssueCard({ issue, auditId, repoPath }) {
  const [copied, setCopied] = useState(false);
  const color = COLORS[issue.severity] || COLORS.low;

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(issue.fixPrompt || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      // Clipboard API can fail without permission/https - the prompt is still selectable text.
    }
  }

  const before = issue.evidence && issue.evidence.screenshotBefore;
  const after = issue.evidence && issue.evidence.screenshotAfter;

  return (
    <article className="issue-card" style={{ borderLeftColor: color }}>
      <div className="issue-card-head">
        <SeverityBadge severity={issue.severity} />
        <span>{issue.category}</span>
        {issue.regressionStatus && (
          <span className={`regression-tag ${issue.regressionStatus}`}>{issue.regressionStatus}</span>
        )}
        <span style={{ marginLeft: 'auto' }}>confidence {Math.round((issue.confidence || 0) * 100)}%</span>
      </div>

      <h3>{issue.title}</h3>
      {issue.route && <p className="issue-route">{issue.route}</p>}
      {issue.description && <p>{issue.description}</p>}

      {issue.reproductionSteps && issue.reproductionSteps.length > 0 && (
        <>
          <h4>Reproduction</h4>
          <ol>
            {issue.reproductionSteps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </>
      )}

      {(issue.expected || issue.actual) && (
        <div className="two-col">
          <div>
            <h4>Expected</h4>
            <p>{issue.expected}</p>
          </div>
          <div>
            <h4>Actual</h4>
            <p>{issue.actual}</p>
          </div>
        </div>
      )}

      {issue.likelyRootCause && (
        <>
          <h4>Likely root cause</h4>
          <p>{issue.likelyRootCause}</p>
        </>
      )}

      {(before || after) && (
        <>
          <h4>Evidence</h4>
          <div className="evidence-shots">
            {before && (
              <figure>
                <img src={evidenceUrl(auditId, before)} alt="Before" />
                <figcaption>Before</figcaption>
              </figure>
            )}
            {after && (
              <figure>
                <img src={evidenceUrl(auditId, after)} alt="After" />
                <figcaption>After</figcaption>
              </figure>
            )}
          </div>
        </>
      )}

      {issue.fixPrompt && (
        <>
          <h4>Fix prompt</h4>
          <div className="fix-prompt-block">
            <pre>{issue.fixPrompt}</pre>
            <button type="button" className="copy-btn" onClick={copyPrompt}>
              {copied ? 'Copied' : 'Copy fix prompt'}
            </button>
          </div>
        </>
      )}

      <FixAttemptPanel auditId={auditId} issue={issue} canFix={!!repoPath} />
    </article>
  );
}
