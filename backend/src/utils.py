import os
import sys
from datetime import datetime, timezone

def timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def format_log(level, scope, message):
    return f"[{timestamp()}] [{level}] [{scope}] {message}"

class Logger:
    def __init__(self, scope):
        self.scope = scope

    def info(self, message):
        print(format_log('INFO', self.scope, message), flush=True)

    def warn(self, message):
        print(format_log('WARN', self.scope, message), file=sys.stderr, flush=True)

    def error(self, message):
        print(format_log('ERROR', self.scope, message), file=sys.stderr, flush=True)

    def debug(self, message):
        if os.environ.get('DEBUG'):
            print(format_log('DEBUG', self.scope, message), flush=True)

def make_logger(scope):
    return Logger(scope)
