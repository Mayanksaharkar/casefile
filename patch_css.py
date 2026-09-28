import re

with open("frontend/app/globals.css", "r") as f:
    content = f.read()

# Replace variables block
new_vars = """
:root {
  --bg: #09090b;
  --bg-secondary: #121214;
  --bg-tertiary: #18181b;
  
  --text: #f4f4f5;
  --text-secondary: #a1a1aa;
  
  --brand: #3b82f6;
  --brand-hover: #60a5fa;
  --brand-glow: rgba(59, 130, 246, 0.4);
  
  --border: #27272a;
  --line-strong: #3f3f46;
  
  --paper: #09090b;
  
  --success: #10b981;
  --danger: #ef4444;
  --warning: #f59e0b;
  
  --radius: 12px;
  --font-mono: 'Geist Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}

body {
  background-color: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  background-image: radial-gradient(circle at 50% 0%, rgba(59, 130, 246, 0.05) 0%, transparent 50%);
}

a {
  color: var(--brand);
  text-decoration: none;
  transition: all 0.2s ease;
}

a:hover {
  color: var(--brand-hover);
  text-shadow: 0 0 8px var(--brand-glow);
}

input[type="text"], input[type="url"], input[type="password"], input[type="number"], textarea, select {
  background: var(--bg-tertiary);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.95rem;
  transition: all 0.2s ease;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
}

input:focus, textarea:focus, select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-glow), inset 0 2px 4px rgba(0,0,0,0.2);
}

.submit-btn {
  background: linear-gradient(135deg, var(--brand), #2563eb);
  color: white;
  border: none;
  padding: 1rem 2rem;
  border-radius: 8px;
  font-weight: 600;
  font-size: 1.05rem;
  cursor: pointer;
  box-shadow: 0 4px 14px 0 rgba(59, 130, 246, 0.39);
  transition: all 0.3s ease;
  width: 100%;
}

.submit-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.5);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.card {
  background: rgba(24, 24, 27, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}

.hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
  display: block;
  margin-top: 0.5rem;
  line-height: 1.4;
}

code {
  font-family: var(--font-mono);
  background: var(--bg-tertiary);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-size: 0.9em;
  color: #a78bfa;
}
"""

content = re.sub(r':root\s*\{.*?\}(?=\s*body)', new_vars, content, flags=re.DOTALL)
content = re.sub(r'body\s*\{.*?\}(?=\s*a)', "", content, flags=re.DOTALL) 
content = re.sub(r'input\[type="text"\].*?(?=\.hint)', "", content, flags=re.DOTALL)
content = re.sub(r'\.card\s*\{.*?\}', "", content, flags=re.DOTALL)
content = re.sub(r'\.submit-btn\s*\{.*?\}', "", content, flags=re.DOTALL)
content = re.sub(r'\.submit-btn:hover\s*\{.*?\}', "", content, flags=re.DOTALL)
content = re.sub(r'\.submit-btn:disabled\s*\{.*?\}', "", content, flags=re.DOTALL)

# Let's just completely overwrite globals.css for a clean slate
with open("frontend/app/globals.css", "w") as f:
    f.write(new_vars)

