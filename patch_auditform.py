import os
import re

with open("frontend/components/AuditForm.js", "r") as f:
    content = f.read()

# Add framer-motion and lucide-react imports
if "framer-motion" not in content:
    content = "import { motion, AnimatePresence } from 'framer-motion';\nimport { Shield, LayoutDashboard, Terminal, CheckCircle2 } from 'lucide-react';\n" + content

# Wrap the form in a motion.form and add animated tabs
# We'll replace the old tabs block we added in phase 1 with Framer Motion tabs
old_tabs_regex = r"<div style=\{\{ display: 'flex', gap: '1rem', marginBottom: '1\.5rem'.*?</div>\s*\}\)"
new_tabs = """
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
"""

content = re.sub(old_tabs_regex, new_tabs, content, flags=re.DOTALL)

# Wrap elements inside <form> with staggered motion variants
# For simplicity, we just change `<form ` to `<motion.form initial={{opacity:0}} animate={{opacity:1}} transition={{staggerChildren:0.1}} `
content = content.replace('<form className="audit-form" onSubmit={handleSubmit}>', '<motion.form className="audit-form" onSubmit={handleSubmit} initial={{opacity:0}} animate={{opacity:1}} transition={{duration: 0.4}}>')
content = content.replace('</form>', '</motion.form>')

# Update the start button
submit_btn_regex = r'<button type="submit" className="submit-btn" disabled=\{submitting\}>.*?</button>'
new_btn = """
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
"""
content = re.sub(submit_btn_regex, new_btn, content, flags=re.DOTALL)

with open("frontend/components/AuditForm.js", "w") as f:
    f.write(content)
