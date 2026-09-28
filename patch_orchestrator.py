import re

with open("backend/src/orchestrator.py", "r") as f:
    content = f.read()

# Add import for source_mapper
if "source_mapper" not in content:
    content = content.replace("from src.discovery import analyze_repo", "from src.discovery import analyze_repo\nfrom src.source_mapper import generate_test_vectors")

# Find the spot where analyze_repo is called
inject = """
        if repo_path:
            push_log(state, f"Analyzing repository at {repo_path}")
            state['repoAnalysis'] = analyze_repo(repo_path)
            
            push_log(state, f"[Source-Aware] Mapping routes and generating test vectors from {repo_path}")
            try:
                vectors = generate_test_vectors(repo_path)
                state['testVectors'] = vectors
                push_log(state, f"[Source-Aware] Found {len(vectors)} test vectors from codebase.")
            except Exception as e:
                push_log(state, f"[Source-Aware] Failed to generate test vectors: {str(e)}")
"""

content = re.sub(r'\s*if repo_path:\s*push_log\(state, f"Analyzing repository at \{repo_path\}"\)\s*state\[\'repoAnalysis\'\] = analyze_repo\(repo_path\)', inject, content)

with open("backend/src/orchestrator.py", "w") as f:
    f.write(content)
