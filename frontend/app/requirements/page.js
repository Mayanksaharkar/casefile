'use client';

import { useState, useEffect } from 'react';

export default function RequirementsPage() {
  const [targetApp, setTargetApp] = useState('');
  const [source, setSource] = useState('manual');
  const [rawText, setRawText] = useState('');
  const [loading, setLoading] = useState(false);
  const [requirements, setRequirements] = useState([]);

  useEffect(() => {
    if (targetApp) {
      fetch(`/api/requirements/${encodeURIComponent(targetApp)}`)
        .then(res => res.json())
        .then(data => setRequirements(data))
        .catch(err => console.error(err));
    }
  }, [targetApp]);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch('/api/requirements/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_app: targetApp, source, raw_text: rawText })
      });
      const newReq = await res.json();
      setRequirements([newReq, ...requirements]);
      setRawText('');
    } catch (err) {
      alert('Error saving requirement: ' + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRunTestCase(testCase) {
    try {
      const res = await fetch('/api/audits/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          targetUrl: targetApp,
          testCaseId: testCase.id
        })
      });
      const { id } = await res.json();
      window.location.href = `/audits/${id}`;
    } catch (err) {
      alert('Failed to run test case: ' + err.message);
    }
  }

  return (
    <div className="requirements-page" style={{ padding: '2rem' }}>
      <h1>Requirements & Test Plans</h1>
      
      <form onSubmit={handleSubmit} style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', marginBottom: '2rem' }}>
        <h2>Ingest New Requirement</h2>
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
          <input 
            type="text" 
            placeholder="Target URL (e.g. https://example.com)" 
            value={targetApp} 
            onChange={(e) => setTargetApp(e.target.value)}
            required
            style={{ flex: 1, padding: '0.5rem' }}
          />
          <select value={source} onChange={(e) => setSource(e.target.value)} style={{ padding: '0.5rem' }}>
            <option value="manual">Manual Entry</option>
            <option value="jira">Jira Ticket</option>
            <option value="github">GitHub Issue</option>
          </select>
        </div>
        <textarea
          placeholder="Paste user story, acceptance criteria, or PRD excerpt here..."
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          required
          rows={6}
          style={{ width: '100%', padding: '0.5rem', marginBottom: '1rem' }}
        />
        <button type="submit" disabled={loading} style={{ background: '#3b82f6', color: 'white', padding: '0.5rem 1rem', border: 'none', borderRadius: '4px' }}>
          {loading ? 'Processing via AI...' : 'Generate Test Cases'}
        </button>
      </form>

      <div className="requirements-list">
        <h2>Existing Test Plans</h2>
        {requirements.length === 0 ? (
          <p>No requirements found for this target app.</p>
        ) : requirements.map(req => (
          <div key={req.id} style={{ background: '#1e1e1e', padding: '1rem', borderRadius: '8px', marginBottom: '1rem' }}>
            <span style={{ fontSize: '0.8rem', color: '#888' }}>Source: {req.source}</span>
            <p style={{ margin: '0.5rem 0', whiteSpace: 'pre-wrap' }}>{req.raw_text}</p>
            <div style={{ marginTop: '1rem', borderTop: '1px solid #333', paddingTop: '1rem' }}>
              <strong>Generated Test Cases:</strong>
              <ul style={{ paddingLeft: '1.5rem', marginTop: '0.5rem' }}>
                {req.test_cases?.map(tc => (
                  <li key={tc.id} style={{ marginBottom: '0.5rem' }}>
                    <b>{tc.description}</b>
                    <br/><span style={{ color: '#aaa', fontSize: '0.9em' }}>Expected: {tc.expected_result}</span>
                    <br/><button onClick={() => handleRunTestCase(tc)} style={{ marginTop: '4px', fontSize: '0.8rem', padding: '2px 8px' }}>Execute Test Case →</button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
