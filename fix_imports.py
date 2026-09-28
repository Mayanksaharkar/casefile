import os
import re
from pathlib import Path

def process_file(filepath):
    content = filepath.read_text(encoding='utf-8')
    
    # from src.utils.logger -> from src.utils
    content = re.sub(r'from\s+src\.utils\.logger\s+import', 'from src.utils import', content)
    # from ..utils.logger -> from ..utils
    content = re.sub(r'from\s+\.\.utils\.logger\s+import', 'from ..utils import', content)
    # from .utils.logger -> from .utils
    content = re.sub(r'from\s+\.utils\.logger\s+import', 'from .utils import', content)
    
    # from src.storage import diskStorage as storage -> import src.storage as storage
    content = re.sub(r'from\s+src\.storage\s+import\s+diskStorage\s+as\s+storage', 'import src.storage as storage', content)
    content = re.sub(r'from\s+src\.storage\.disk_storage\s+import', 'from src.storage import', content)
    content = re.sub(r'from\s+\.\.storage\s+import\s+disk_storage\s+as\s+storage', 'from .. import storage', content)
    content = re.sub(r'from\s+\.storage\.disk_storage\s+import', 'from .storage import', content)

    # from src.config.auditConfigLoader -> from src.config
    content = re.sub(r'from\s+src\.config\.auditConfigLoader\s+import', 'from src.config import', content)
    
    # from src.discovery.repoAnalyzer -> from src.discovery
    content = re.sub(r'from\s+src\.discovery\.repoAnalyzer\s+import', 'from src.discovery import', content)
    content = re.sub(r'from\s+src\.discovery\.routeDiscovery\s+import', 'from src.discovery import', content)

    # from src.browser.playwrightDriver -> from src.browser_engine
    content = re.sub(r'from\s+src\.browser\.playwrightDriver\s+import', 'from src.browser_engine import', content)
    
    # from src.browser import authHandler -> import src.browser_engine as authHandler (wait, did browser_engine have auth? No, auth is missing or in browser_engine?) Let's check browser_engine.
    
    # from src.intelligence.planner -> from src.intelligence
    content = re.sub(r'from\s+src\.intelligence\.planner\s+import', 'from src.intelligence import', content)
    content = re.sub(r'from\s+src\.intelligence\.bugJudge\s+import', 'from src.intelligence import', content)
    content = re.sub(r'from\s+src\.intelligence\.fixPromptGenerator\s+import', 'from src.intelligence import', content)
    content = re.sub(r'from\s+\.intelligence\.gemini_client\s+import', 'from .intelligence import', content)
    
    # from src.regression.compare -> from src.regression
    content = re.sub(r'from\s+src\.regression\.compare\s+import', 'from src.regression import', content)
    content = re.sub(r'from\s+\.regression\.compare\s+import', 'from .regression import', content)

    # from src.reports.reportGenerator -> from src.reports
    content = re.sub(r'from\s+src\.reports\.reportGenerator\s+import', 'from src.reports import', content)
    
    # .storage.disk_storage -> .storage
    content = re.sub(r'\.storage\.disk_storage', '.storage', content)
    
    filepath.write_text(content, encoding='utf-8')

src_dir = Path("backend/src")
for f in src_dir.rglob("*.py"):
    process_file(f)

print("Imports fixed.")
