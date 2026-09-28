'use client';

import { useState, useMemo, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { listAudits, startAudit } from '../lib/api';
import PromptGenerator from './PromptGenerator';
import { motion, AnimatePresence } from 'framer-motion';
import { Shield, LayoutDashboard, Terminal } from 'lucide-react';

function emptyProfile(index) {
  return {
    name: index === 0 ? 'primary' : `User${index + 1}`,
    loginUrl: '',
    credentialsText: '',
    useSelectors: false,
    username: '',
    password: '',
    usernameSelector: '',
    passwordSelector: '',
    submitSelector: '',
  };
}

export default function AuditForm() {
  const router = useRouter();
  const [targetUrl, setTargetUrl] = useState('http://localhost:3000');
  const [repoPath, setRepoPath] = useState('');
  const [budget, setBudget] = useState(40);
  const [maxPages, setMaxPages] = useState(15);
  const [safeMode, setSafeMode] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const [allAudits, setAllAudits] = useState([]);
  const [compareAgainstId, setCompareAgainstId] = useState('');

  const [needsAuth, setNeedsAuth] = useState(false);
  const [auditMode, setAuditMode] = useState('primary');
  const [authProfiles, setAuthProfiles] = useState([emptyProfile(0)]);

  useEffect(() => {
    let active = true;
    listAudits()
      .then((data) => { if (active) setAllAudits(data); })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  const matchingAudits = useMemo(
    () =>
      allAudits
        .filter((a) => a.targetUrl === targetUrl.trim() && a.status === 'completed')
        .sort((a, b) => new Date(b.startedAt) - new Date(a.startedAt)),
    [allAudits, targetUrl]
  );

  useEffect(() => {
    const id = matchingAudits[0] ? matchingAudits[0].id : '';
    setCompareAgainstId(prev => (prev !== id ? id : prev));
  }, [matchingAudits]);

  function updateProfile(index, patch) {
    setAuthProfiles((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function addProfile() {
    setAuthProfiles((prev) => [...prev, emptyProfile(prev.length)]);
  }

  function removeProfile(index) {
    setAuthProfiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const payload = {
      targetUrl: targetUrl.trim(),
      repoPath: repoPath.trim(),
      budget: Number(budget),
      maxPages: Number(maxPages),
      safeMode,
      compareAgainstId,
      auth: needsAuth
        ? {
            profiles: authProfiles.map((p) => ({
              name: p.name,
              loginUrl: p.loginUrl,
              credentialsText: p.useSelectors ? undefined : p.credentialsText,
              useSelectors: p.useSelectors,
              username: p.useSelectors ? p.username : undefined,
              password: p.useSelectors ? p.password : undefined,
              usernameSelector: p.useSelectors ? p.usernameSelector : undefined,
              passwordSelector: p.useSelectors ? p.passwordSelector : undefined,
              submitSelector: p.useSelectors ? p.submitSelector : undefined,
            })),
          }
        : undefined,
    };

    try {
      const res = await startAudit(payload);
      router.push(`/audits/${res.id}`);
    } catch (err) {
      setError(err.message || 'Failed to start audit');
      setSubmitting(false);
    }
  }

  return (
    <motion.form 
      className="audit-form" 
      onSubmit={handleSubmit}
      initial={{opacity: 0, y: 10}} 
      animate={{opacity: 1, y: 0}} 
      transition={{duration: 0.4}}
    >
      {error && <div className="error">{error}</div>}

      <div style={{ display: 'flex', background: 'var(--bg-tertiary)', padding: '0.25rem', borderRadius: '8px', marginBottom: '1.5rem', position: 'relative' }}>
        <button 
          type="button" 
          onClick={() => setAuditMode('primary')}
          style={{ flex: 1, padding: '0.75rem', position: 'relative', background: 'none', border: 'none', color: auditMode === 'primary' ? '#fff' : 'var(--text-secondary)', fontWeight: 500, cursor: 'pointer', zIndex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
        >
          <LayoutDashboard size={18} /> Source-Aware
          {auditMode === 'primary' && (
            <motion.div layoutId="activeTab" style={{ position: 'absolute', inset: 0, background: 'var(--brand)', borderRadius: '6px', zIndex: -1, boxShadow: '0 0 12px var(--brand-glow)' }} />
          )}
        </button>
        <button 
          type="button" 
          onClick={() => setAuditMode('secondary')}
          style={{ flex: 1, padding: '0.75rem', position: 'relative', background: 'none', border: 'none', color: auditMode === 'secondary' ? '#fff' : 'var(--text-secondary)', fontWeight: 500, cursor: 'pointer', zIndex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
        >
          <Terminal size={18} /> Dynamic Crawl
          {auditMode === 'secondary' && (
            <motion.div layoutId="activeTab" style={{ position: 'absolute', inset: 0, background: 'var(--brand)', borderRadius: '6px', zIndex: -1, boxShadow: '0 0 12px var(--brand-glow)' }} />
          )}
        </button>
      </div>

      <AnimatePresence mode="wait">
        {auditMode === 'primary' ? (
          <motion.div 
            key="primary"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            style={{ marginBottom: '1.5rem', padding: '1rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}
          >
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
              <Shield size={20} color="var(--brand)" style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <strong style={{ color: '#fff', display: 'block', marginBottom: '0.25rem' }}>Deterministic Mapping Active</strong>
                <span className="hint" style={{ marginTop: 0 }}>Casefile will parse the routing tree and components to generate a 100% coverage map before opening the browser. <em>Repository Path is required.</em></span>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div 
            key="secondary"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            style={{ marginBottom: '1.5rem' }}
          >
            <div style={{ padding: '1rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              <strong style={{ color: '#fff', display: 'block', marginBottom: '0.25rem' }}>Exploratory Mode</strong>
              <span className="hint" style={{ marginTop: 0 }}>Standard black-box crawl. Uses <code>.audit/auditcontext.md</code> for guidance if present.</span>
            </div>
            <PromptGenerator />
          </motion.div>
        )}
      </AnimatePresence>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="targetUrl" style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text)', fontWeight: 500 }}>Target URL</label>
          <input id="targetUrl" type="url" required value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div style={{ flex: 1 }}>
          <label htmlFor="repoPath" style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text)', fontWeight: 500 }}>Repository Path</label>
          <input id="repoPath" type="text" value={repoPath} onChange={(e) => setRepoPath(e.target.value)} style={{ width: '100%' }} placeholder="/absolute/path/to/repo" required={auditMode === 'primary'} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="budget" style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text)', fontWeight: 500 }}>Action Budget</label>
          <input id="budget" type="number" value={budget} onChange={(e) => setBudget(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div style={{ flex: 1 }}>
          <label htmlFor="maxPages" style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text)', fontWeight: 500 }}>Max Pages</label>
          <input id="maxPages" type="number" value={maxPages} onChange={(e) => setMaxPages(e.target.value)} style={{ width: '100%' }} />
        </div>
      </div>
      
      <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '2rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text)', cursor: 'pointer' }}>
          <input type="checkbox" checked={safeMode} onChange={(e) => setSafeMode(e.target.checked)} style={{ width: '18px', height: '18px', accentColor: 'var(--brand)' }} />
          Safe Mode (Skip destructive actions)
        </label>
        
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text)', cursor: 'pointer' }}>
          <input type="checkbox" checked={needsAuth} onChange={(e) => setNeedsAuth(e.target.checked)} style={{ width: '18px', height: '18px', accentColor: 'var(--brand)' }} />
          Requires Authentication
        </label>
      </div>

      <motion.button 
        type="submit" 
        className="submit-btn" 
        disabled={submitting}
        whileHover={!submitting ? { scale: 1.02 } : {}}
        whileTap={!submitting ? { scale: 0.98 } : {}}
      >
        {submitting ? (
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}>
             <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}>⚙</motion.div> Starting Audit...
          </span>
        ) : (
          'Initialize Audit Sequence'
        )}
      </motion.button>
    </motion.form>
  );
}
