'use client';

import { useState } from 'react';
import FixtureVault from '../../components/FixtureVault';

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState('integrations');
  const [testStatus, setTestStatus] = useState(null);
  const [isTesting, setIsTesting] = useState(false);

  async function handleTestLLM() {
    setIsTesting(true);
    setTestStatus(null);
    try {
      const res = await fetch('http://localhost:4001/api/system/test-llm');
      const data = await res.json();
      if (data.ok) {
        setTestStatus({ type: 'success', text: `✅ AI Engine is configured and live! Response: "${data.message}"` });
      } else {
        setTestStatus({ type: 'error', text: `❌ AI Engine error: ${data.error}` });
      }
    } catch (err) {
      setTestStatus({ type: 'error', text: `❌ Failed to connect to server: ${err.message}` });
    } finally {
      setIsTesting(false);
    }
  }

  return (
    <div className="config-page" style={{ padding: '2rem' }}>
      <h1>Settings & Integrations</h1>
      
      <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid #333', marginBottom: '2rem' }}>
        {['ai', 'integrations', 'ci', 'auth', 'fixtures'].map(tab => (
          <button 
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{ 
              padding: '0.5rem 1rem', 
              background: 'transparent', 
              border: 'none', 
              borderBottom: activeTab === tab ? '2px solid #3b82f6' : '2px solid transparent',
              color: activeTab === tab ? '#fff' : '#aaa',
              cursor: 'pointer',
              textTransform: 'capitalize'
            }}>
            {tab === 'ai' ? 'AI Engine' : tab === 'fixtures' ? 'Fixture Vault' : tab}
          </button>
        ))}
      </div>

      {activeTab === 'ai' && (
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px' }}>
          <h2>AI Engine Configuration</h2>
          <p style={{ color: '#aaa', marginBottom: '1.5rem' }}>
            Casefile requires an LLM engine (e.g. OpenRouter, Gemini, OpenAI) to plan tests and evaluate UI findings. 
            Configure your API keys in the backend <code>.env</code> file.
          </p>
          
          <div style={{ marginBottom: '1rem', padding: '1rem', background: '#2a2a2a', borderRadius: '6px' }}>
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>Test Connection</h3>
            <p style={{ color: '#888', fontSize: '0.875rem', marginBottom: '1rem' }}>
              Ping the configured AI model to verify it responds with valid structured JSON.
            </p>
            <button 
              className="btn-primary" 
              onClick={handleTestLLM}
              disabled={isTesting}
              style={{ 
                background: '#3b82f6', color: '#fff', border: 'none', 
                padding: '0.5rem 1rem', borderRadius: '4px', cursor: isTesting ? 'not-allowed' : 'pointer',
                opacity: isTesting ? 0.7 : 1
              }}
            >
              {isTesting ? 'Testing...' : 'Test AI Engine'}
            </button>
            
            {testStatus && (
              <div style={{ 
                marginTop: '1rem', 
                padding: '0.75rem', 
                borderRadius: '4px',
                background: testStatus.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${testStatus.type === 'success' ? '#10b981' : '#ef4444'}`,
                color: testStatus.type === 'success' ? '#34d399' : '#f87171'
              }}>
                {testStatus.text}
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'integrations' && (
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px' }}>
          <h2>Ticket Systems</h2>
          <p style={{ color: '#aaa', marginBottom: '1rem' }}>Casefile will automatically file tickets for new, high-confidence (≥ 90%) critical and high severity findings.</p>
          
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>Linear API Key</label>
            <input type="password" placeholder="lin_api_..." style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #444', background: '#333', color: '#fff' }} />
          </div>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>Linear Team ID</label>
            <input type="text" placeholder="e.g. 123e4567-e89b..." style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #444', background: '#333', color: '#fff' }} />
          </div>
          <button className="btn-primary" style={{ background: '#3b82f6', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}>Save Integrations</button>
        </div>
      )}

      {activeTab === 'ci' && (
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px' }}>
          <h2>CI/CD Gating (GitHub Actions)</h2>
          <p style={{ color: '#aaa', marginBottom: '1rem' }}>Configure thresholds for pulling GitHub commit statuses.</p>
          
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
            <input type="checkbox" defaultChecked />
            Block PR merges on Critical/High severity findings
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
            <input type="checkbox" defaultChecked />
            Post summary comment on PR
          </label>
          <button className="btn-primary" style={{ background: '#3b82f6', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}>Save CI Settings</button>
        </div>
      )}

      {activeTab === 'auth' && (
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px' }}>
          <h2>Target App Credentials</h2>
          <p style={{ color: '#aaa', marginBottom: '1rem' }}>Define user roles and credentials for authenticated exploration.</p>
          <button className="btn-secondary" style={{ background: '#444', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}>+ Add Role</button>
        </div>
      )}

      {activeTab === 'fixtures' && (
        <div className="card" style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px' }}>
          <FixtureVault />
        </div>
      )}
    </div>
  );
}
