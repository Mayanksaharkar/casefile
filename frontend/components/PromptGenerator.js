import { useState } from 'react';
import { motion } from 'framer-motion';
import { Copy, Check, Wand2 } from 'lucide-react';

export default function PromptGenerator() {
  const [featureDesc, setFeatureDesc] = useState('');
  const [copied, setCopied] = useState(false);

  const generatePrompt = () => {
    return `Please generate a \`.audit/auditcontext.md\` file for the following feature/flow:

**Feature Context & Scope:**
${featureDesc}

**Instructions for the IDE Agent:**
1. Map out the architectural context for this feature.
2. Outline the expected test vectors, auth states, and edge cases.
3. Define the specific security and performance bounds Casefile should monitor during the audit.
4. Format the output in markdown and save it precisely to \`.audit/auditcontext.md\` in the root of the workspace.`;
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(generatePrompt());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, type: 'spring' }}
      className="card prompt-gen-card" 
      style={{ marginTop: '1.5rem', position: 'relative', overflow: 'hidden' }}
    >
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: 'linear-gradient(90deg, transparent, var(--brand), transparent)' }} />
      
      <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Wand2 size={18} color="var(--brand)" /> 
        IDE Prompt Generator
      </h3>
      <p className="hint" style={{ marginBottom: '1rem' }}>
        Want Casefile to test specific flows? Describe what to audit, and we'll generate a strict prompt for Cursor/Windsurf to build your <code>auditcontext.md</code>.
      </p>
      
      <motion.textarea
        whileFocus={{ scale: 1.01 }}
        rows={3}
        placeholder="e.g. Test the user checkout flow, including invalid credit cards and empty carts."
        value={featureDesc}
        onChange={(e) => setFeatureDesc(e.target.value)}
        style={{ width: '100%', marginBottom: '1rem', resize: 'vertical' }}
      />
      
      <motion.button 
        type="button" 
        onClick={handleCopy}
        disabled={!featureDesc.trim()}
        whileHover={featureDesc.trim() ? { scale: 1.02 } : {}}
        whileTap={featureDesc.trim() ? { scale: 0.98 } : {}}
        style={{ 
          background: copied ? 'var(--success)' : 'rgba(59, 130, 246, 0.1)', 
          color: copied ? '#fff' : 'var(--brand)',
          border: `1px solid ${copied ? 'var(--success)' : 'var(--brand)'}`,
          padding: '0.5rem 1rem',
          borderRadius: '6px',
          cursor: featureDesc.trim() ? 'pointer' : 'not-allowed',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          fontWeight: 500,
          opacity: featureDesc.trim() ? 1 : 0.5,
          transition: 'background 0.2s, color 0.2s, border 0.2s'
        }}
      >
        {copied ? <Check size={16} /> : <Copy size={16} />}
        {copied ? 'Copied to Clipboard!' : 'Copy Prompt for IDE'}
      </motion.button>
    </motion.div>
  );
}
