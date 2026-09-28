import os
import json
import re
import logging
import inspect
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger('discovery')

# ---------------------------------------------------------
# repoAnalyzer.py
# ---------------------------------------------------------

CODE_EXTENSIONS = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'}
IGNORED_DIRS = {'node_modules', '.next', '.git', 'dist', 'build', 'coverage', '.audit'}
MAX_FILES = 4000

def walk(dir_path: str, files: Optional[List[str]] = None) -> List[str]:
    if files is None:
        files = []
    
    try:
        entries = os.scandir(dir_path)
    except Exception:
        return files

    with entries:
        for entry in entries:
            if len(files) >= MAX_FILES:
                break
            if entry.name in IGNORED_DIRS:
                continue
            
            full = os.path.join(dir_path, entry.name)
            if entry.is_dir(follow_symlinks=False):
                walk(full, files)
            elif os.path.splitext(entry.name)[1] in CODE_EXTENSIONS:
                files.append(full)
                
    return files

def detect_framework(repo_path: str) -> Dict[str, Any]:
    pkg_path = os.path.join(repo_path, 'package.json')
    if not os.path.exists(pkg_path):
        return {'name': 'unknown', 'deps': {}}
    try:
        with open(pkg_path, 'r', encoding='utf-8') as f:
            pkg = json.load(f)
        deps = {}
        deps.update(pkg.get('dependencies') or {})
        deps.update(pkg.get('devDependencies') or {})
        
        if 'next' in deps:
            return {'name': 'next', 'deps': deps}
        if 'express' in deps:
            return {'name': 'express', 'deps': deps}
        return {'name': 'unknown', 'deps': deps}
    except Exception:
        return {'name': 'unknown', 'deps': {}}

def next_segment_to_url(segment: str) -> Optional[str]:
    if segment.startswith('(') and segment.endswith(')'):
        return None
    if segment.startswith('[...') and segment.endswith(']'):
        return '*'
    if segment.startswith('[') and segment.endswith(']'):
        return f":{segment[1:-1]}"
    return segment

def extract_exported_http_methods(file_path: str) -> List[str]:
    src = safe_read(file_path)
    if not src:
        return []
    methods = []
    for m in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD']:
        re_str = rf"export\s+(async\s+)?function\s+{m}\b|export\s+const\s+{m}\s*="
        if re.search(re_str, src):
            methods.append(m)
    return methods

def safe_read(file_path: str) -> Optional[str]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def dedupe_routes(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for r in routes:
        key = f"{r.get('method')} {r.get('path')}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped

def discover_next_routes(repo_path: str) -> List[Dict[str, Any]]:
    routes = []
    for root_name in ['app', 'src/app', 'pages', 'src/pages']:
        root = os.path.join(repo_path, root_name)
        if not os.path.exists(root):
            continue
        
        is_app_router = root_name.endswith('app')
        files = walk(root)
        
        for file in files:
            rel = os.path.relpath(file, root)
            base = os.path.basename(file)
            
            if is_app_router:
                # App router: a route exists where page.js / page.tsx lives.
                if not re.match(r"^page\.(js|jsx|ts|tsx)$", base):
                    continue
                dirname = os.path.dirname(rel) or '.'
                parts = dirname.split(os.sep)
                segments = [next_segment_to_url(s) for s in parts if s != '.']
                segments = [s for s in segments if s is not None]
                
                url_path = '/' + '/'.join(segments)
                url_path = re.sub(r"/+", "/", url_path)
                if not url_path:
                    url_path = '/'
                
                routes.append({
                    'path': url_path, 
                    'method': 'GET', 
                    'sourceFile': os.path.relpath(file, repo_path), 
                    'kind': 'page'
                })
            else:
                # Pages router: any file (excluding _app/_document/api) is a page route.
                if re.match(r"^_(app|document)\.", base):
                    continue
                if rel.startswith(f"api{os.sep}") or rel == 'api':
                    continue
                
                without_ext = re.sub(r"\.(js|jsx|ts|tsx)$", "", rel)
                segments = [next_segment_to_url(s) for s in without_ext.split(os.sep)]
                segments = [s for s in segments if s is not None]
                
                url_path = '/' + '/'.join(segments)
                url_path = re.sub(r"/index$", "", url_path)
                if not url_path:
                    url_path = '/'
                url_path = re.sub(r"/+", "/", url_path)
                
                routes.append({
                    'path': url_path, 
                    'method': 'GET', 
                    'sourceFile': os.path.relpath(file, repo_path), 
                    'kind': 'page'
                })

        # API routes: app/**/api/**/route.js (App Router) or pages/api/** (Pages Router)
        for file in files:
            rel = os.path.relpath(file, root)
            base = os.path.basename(file)
            
            if is_app_router and re.match(r"^route\.(js|jsx|ts|tsx)$", base) and f"api{os.sep}" in rel:
                dirname = os.path.dirname(rel) or '.'
                segments = [next_segment_to_url(s) for s in dirname.split(os.sep)]
                segments = [s for s in segments if s is not None]
                
                url_path = '/' + '/'.join(segments)
                url_path = re.sub(r"/+", "/", url_path)
                
                methods = extract_exported_http_methods(file)
                if not methods:
                    methods = ['GET']
                for method in methods:
                    routes.append({
                        'path': url_path, 
                        'method': method, 
                        'sourceFile': os.path.relpath(file, repo_path), 
                        'kind': 'api'
                    })
            elif not is_app_router and rel.startswith(f"api{os.sep}"):
                without_ext = re.sub(r"\.(js|jsx|ts|tsx)$", "", rel)
                segments = [next_segment_to_url(s) for s in without_ext.split(os.sep)]
                segments = [s for s in segments if s is not None]
                
                url_path = '/' + '/'.join(segments)
                url_path = re.sub(r"/+", "/", url_path)
                
                routes.append({
                    'path': url_path, 
                    'method': 'ANY', 
                    'sourceFile': os.path.relpath(file, repo_path), 
                    'kind': 'api'
                })

    return dedupe_routes(routes)

EXPRESS_ROUTE_RE = re.compile(r"\b(?:app|router)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*(['\"])([^'\"]+)\2", re.IGNORECASE)

def discover_express_routes(repo_path: str) -> List[Dict[str, Any]]:
    routes = []
    files = walk(repo_path)
    for file in files:
        src = safe_read(file)
        if not src:
            continue
        for match in EXPRESS_ROUTE_RE.finditer(src):
            routes.append({
                'path': match.group(3),
                'method': match.group(1).upper(),
                'sourceFile': os.path.relpath(file, repo_path),
                'kind': 'api'
            })
    return dedupe_routes(routes)

FETCH_CALL_RE = re.compile(r"\b(?:fetch|axios\.(?:get|post|put|patch|delete))\s*\(\s*(['\"])([^'\"]+)\1")

def discover_client_api_calls(repo_path: str) -> List[Dict[str, Any]]:
    calls = []
    files = walk(repo_path)
    for file in files:
        src = safe_read(file)
        if not src:
            continue
        for match in FETCH_CALL_RE.finditer(src):
            url = match.group(2)
            if url.startswith('/') or '/api/' in url:
                calls.append({
                    'url': url, 
                    'sourceFile': os.path.relpath(file, repo_path)
                })
                
    seen = set()
    deduped = []
    for c in calls:
        key = f"{c['url']}::{c['sourceFile']}"
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped

def analyze_repo(repo_path: str) -> Optional[Dict[str, Any]]:
    if not repo_path:
        return None
    if not os.path.exists(repo_path):
        logger.warning(f"repoPath does not exist: {repo_path}")
        return {'error': f"repoPath does not exist: {repo_path}"}

    framework = detect_framework(repo_path)
    routes = []
    
    if framework['name'] == 'next':
        routes = discover_next_routes(repo_path)
        express_routes = [r for r in discover_express_routes(repo_path) if r.get('kind') == 'api']
        routes.extend(express_routes)
    elif framework['name'] == 'express':
        routes = discover_express_routes(repo_path)
    else:
        routes = discover_next_routes(repo_path) + discover_express_routes(repo_path)

    client_api_calls = discover_client_api_calls(repo_path)
    api_endpoints = dedupe_routes([r for r in routes if r.get('kind') == 'api'])
    pages = dedupe_routes([r for r in routes if r.get('kind') == 'page'])

    logger.info(
        f"Repo analysis ({framework['name']}): {len(pages)} pages, "
        f"{len(api_endpoints)} api endpoints, {len(client_api_calls)} client fetch call sites"
    )

    return {
        'framework': framework['name'],
        'pages': pages,
        'apiEndpoints': api_endpoints,
        'clientApiCalls': client_api_calls,
    }

# ---------------------------------------------------------
# routeDiscovery.py
# ---------------------------------------------------------

def same_origin(base: str, candidate: str) -> bool:
    try:
        base_url = urlparse(base)
        candidate_url = urlparse(urljoin(base, candidate))
        return base_url.scheme == candidate_url.scheme and base_url.netloc == candidate_url.netloc
    except Exception:
        return False

def normalize(base: str, href: str) -> Optional[str]:
    try:
        url = urlparse(urljoin(base, href))
        url = url._replace(fragment='')
        return url.geturl()
    except Exception:
        return None

async def discover_app(driver: Any, base_url: str, max_pages: int = 15, on_page: Optional[Callable] = None) -> List[Dict[str, Any]]:
    visited = set()
    queue = [base_url]
    pages = []

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        normalized_url = normalize(base_url, url)
        if not normalized_url or normalized_url in visited:
            continue
            
        visited.add(normalized_url)

        try:
            await driver.goto(normalized_url)
        except Exception as err:
            logger.warning(f"Could not load {normalized_url}: {err}")
            continue

        title = await driver.title()
        
        # Async calls as requested
        elements = await driver.get_interactive_elements()
        state_hash = await driver.compute_state_hash(elements)

        page_info = {
            'url': normalized_url,
            'title': title,
            'stateHash': state_hash,
            'buttons': elements.get('buttons', []),
            'forms': elements.get('forms', []),
        }
        pages.append(page_info)
        
        if on_page:
            if inspect.iscoroutinefunction(on_page):
                await on_page(page_info)
            else:
                on_page(page_info)

        for link in elements.get('links', []):
            href = link.get('href') if isinstance(link, dict) else getattr(link, 'href', None)
            if not href:
                continue
            
            abs_url = normalize(base_url, href)
            if not abs_url:
                continue
            if not same_origin(base_url, abs_url):
                continue
            if '#' in abs_url:
                continue
            if re.match(r"^(mailto|tel|javascript):", href):
                continue
            if abs_url not in visited and abs_url not in queue:
                queue.append(abs_url)

    logger.info(f"Discovery crawl finished: {len(pages)} pages found (visited {len(visited)} URLs)")
    return pages
