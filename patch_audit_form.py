import re

with open("frontend/components/AuditForm.js", "r") as f:
    content = f.read()

# Add PromptGenerator import
if "PromptGenerator" not in content:
    content = content.replace("import { listAudits, startAudit } from '../lib/api';", "import { listAudits, startAudit } from '../lib/api';\nimport PromptGenerator from './PromptGenerator';")

# Add state
if "auditMode" not in content:
    content = content.replace("const [needsAuth, setNeedsAuth] = useState(false);", "const [needsAuth, setNeedsAuth] = useState(false);\n  const [auditMode, setAuditMode] = useState('primary');")

# Add the tabs UI right after the <form> starts
tabs_ui = """
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem' }}>
        <button 
          type="button" 
          onClick={() => setAuditMode('primary')}
          style={{ background: 'none', border: 'none', fontWeight: auditMode === 'primary' ? 'bold' : 'normal', color: auditMode === 'primary' ? 'var(--text)' : 'var(--text-secondary)', cursor: 'pointer', fontSize: '1rem', borderBottom: auditMode === 'primary' ? '2px solid var(--brand)' : 'none' }}
        >
          Primary: Source-Aware Audit
        </button>
        <button 
          type="button" 
          onClick={() => setAuditMode('secondary')}
          style={{ background: 'none', border: 'none', fontWeight: auditMode === 'secondary' ? 'bold' : 'normal', color: auditMode === 'secondary' ? 'var(--text)' : 'var(--text-secondary)', cursor: 'pointer', fontSize: '1rem', borderBottom: auditMode === 'secondary' ? '2px solid var(--brand)' : 'none' }}
        >
          Secondary: Dynamic Crawl
        </button>
      </div>

      {auditMode === 'primary' ? (
        <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--paper)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <strong>Source-Aware Mapping:</strong> Casefile will parse the routing tree and components to generate a deterministic 100% coverage map before opening the browser. <em>Repo path is required.</em>
        </div>
      ) : (
        <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--paper)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <strong>Dynamic Crawl:</strong> Standard exploratory audit. Uses <code>.audit/auditcontext.md</code> (if available) for guidance.
          <PromptGenerator />
        </div>
      )}
"""

content = re.sub(r'(<form className="audit-form" onSubmit=\{handleSubmit\}>)', r'\1' + '\n' + tabs_ui, content)

with open("frontend/components/AuditForm.js", "w") as f:
    f.write(content)
