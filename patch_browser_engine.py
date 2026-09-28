import re

with open("backend/src/browser_engine.py", "r") as f:
    content = f.read()

class_alias_block = """
    # Aliases for snake_case compatibility with orchestrator
    spawn_sibling = spawnSibling
    start_tracing = startTracing
    stop_tracing = stopTracing
    console_since = consoleSince
    network_since = networkSince
    clear_logs = clearLogs
    current_url = currentUrl
    accessibility_snapshot = accessibilitySnapshot
    get_interactive_elements = getInteractiveElements
    compute_state_hash = computeStateHash
    screenshot_buffer = screenshotBuffer
    select_option = selectOption
    select_first_option = selectFirstOption
    wait_briefly = waitBriefly
    run_axe = runAxe
    is_dangerous = isDangerous

"""

content = content.replace("def resolveStorageStatePath", class_alias_block + "def resolveStorageStatePath")

with open("backend/src/browser_engine.py", "w") as f:
    f.write(content)
