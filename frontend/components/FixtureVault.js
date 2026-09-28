'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../lib/api';

async function apiRequest(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export default function FixtureVault({ targetApp }) {
  const [fixtures, setFixtures] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Add fixture form state
  const [adding, setAdding] = useState(false);
  const [newField, setNewField] = useState({ field_key: '', value: '', field_type: 'text', vault_type: 'ephemeral' });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = targetApp
        ? `/api/hitl/fixtures/app/${encodeURIComponent(targetApp)}`
        : '/api/hitl/fixtures';
      const data = await apiRequest(url);
      setFixtures(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [targetApp]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id) {
    if (!confirm('Delete this fixture?')) return;
    try {
      await apiRequest(`/api/hitl/fixtures/${id}`, { method: 'DELETE' });
      setFixtures(f => f.filter(fx => fx.id !== id));
    } catch (e) {
      alert('Failed to delete: ' + e.message);
    }
  }

  async function handleSave() {
    if (!newField.field_key.trim() || !newField.value.trim()) return;
    setSaving(true);
    try {
      const body = {
        target_app: targetApp || 'global',
        field_key: newField.field_key.trim(),
        value: newField.value.trim(),
        field_type: newField.field_type,
        vault_type: newField.vault_type,
      };
      const created = await apiRequest('/api/hitl/fixtures', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setFixtures(f => [...f, created]);
      setAdding(false);
      setNewField({ field_key: '', value: '', field_type: 'text', vault_type: 'ephemeral' });
    } catch (e) {
      alert('Failed to save fixture: ' + e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixture-vault">
      <div className="fixture-vault-header">
        <h3>Fixture Vault</h3>
        <button onClick={() => setAdding(a => !a)} className="btn-secondary" style={{ fontSize: '0.85rem', padding: '0.25rem 0.75rem' }}>
          {adding ? 'Cancel' : '+ Add Fixture'}
        </button>
      </div>
      <p style={{ color: '#aaa', fontSize: '0.875rem', marginBottom: '1rem' }}>
        Static fixtures are auto-filled in future runs without asking. Ephemeral fixtures are shown as hints but never auto-applied.
        OTP / one-time codes are always treated as ephemeral regardless of this setting.
      </p>

      {adding && (
        <div className="fixture-add-form">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Field Key (selector or label)</label>
              <input
                type="text"
                value={newField.field_key}
                onChange={e => setNewField(f => ({...f, field_key: e.target.value}))}
                placeholder="e.g. input[name='email'] or Email Address"
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Value</label>
              <input
                type="text"
                value={newField.value}
                onChange={e => setNewField(f => ({...f, value: e.target.value}))}
                placeholder="The value to fill"
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Field Type</label>
              <select value={newField.field_type} onChange={e => setNewField(f => ({...f, field_type: e.target.value}))} style={{ width: '100%' }}>
                <option value="text">text</option>
                <option value="email">email</option>
                <option value="password">password</option>
                <option value="otp">otp</option>
                <option value="select">select</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Vault Type</label>
              <select value={newField.vault_type} onChange={e => setNewField(f => ({...f, vault_type: e.target.value}))} style={{ width: '100%' }}>
                <option value="ephemeral">Ephemeral</option>
                <option value="static">Static (auto-fill)</option>
              </select>
            </div>
          </div>
          <button onClick={handleSave} disabled={saving} className="btn-primary" style={{ background: '#3b82f6', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}>
            {saving ? 'Saving…' : 'Save Fixture'}
          </button>
        </div>
      )}

      {loading && <p style={{ color: '#aaa' }}>Loading fixtures…</p>}
      {error && <div className="hitl-error">{error}</div>}

      {!loading && fixtures.length === 0 && (
        <p style={{ color: '#666', fontSize: '0.875rem' }}>No fixtures stored yet.</p>
      )}

      {fixtures.length > 0 && (
        <table className="fixture-table">
          <thead>
            <tr>
              <th>Field Key</th>
              <th>Type</th>
              <th>Value (masked)</th>
              <th>Vault</th>
              <th>Last Verified</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {fixtures.map(fx => (
              <tr key={fx.id}>
                <td><code style={{ fontSize: '0.8rem' }}>{fx.field_key}</code></td>
                <td><span className="fixture-type-badge">{fx.field_type}</span></td>
                <td><span style={{ fontFamily: 'monospace', color: '#888' }}>{fx.value}</span></td>
                <td>
                  <span className={`fixture-vault-badge ${fx.vault_type}`}>
                    {fx.vault_type === 'static' ? '⚡ Static' : '🔁 Ephemeral'}
                  </span>
                </td>
                <td style={{ fontSize: '0.8rem', color: '#666' }}>
                  {fx.last_verified ? new Date(fx.last_verified).toLocaleDateString() : '—'}
                </td>
                <td>
                  <button onClick={() => handleDelete(fx.id)} style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '0.85rem' }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
