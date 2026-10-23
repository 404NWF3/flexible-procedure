"""Candidate side: no model import, no environment seed, no stage identifier."""
import json
import math
import random
import signal
import socket
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import lock_down


def timeout(*_):
    raise TimeoutError('decision budget exceeded')

# Trusted boot reads code as text only; it is never executed before lockdown.
source = Path(sys.argv[1]).read_text()
compiled = compile(source, '<frozen-candidate>', 'exec')
signal.signal(signal.SIGALRM, timeout)
signal.signal(signal.SIGPROF, timeout)
lock_down()
namespace = {'math': math, 'random': random, '__name__': 'candidate'}
signal.setitimer(signal.ITIMER_REAL, 1)
signal.setitimer(signal.ITIMER_PROF, .25)
exec(compiled, namespace)
signal.setitimer(signal.ITIMER_REAL, 0)
signal.setitimer(signal.ITIMER_PROF, 0)
print(json.dumps({'ready': True}), flush=True)
for line in sys.stdin:
    try:
        observation = json.loads(line)
        signal.setitimer(signal.ITIMER_REAL, 1)
        signal.setitimer(signal.ITIMER_PROF, .25)
        action = namespace['decide'](observation)
        response = json.dumps({'action': action}, allow_nan=False)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.setitimer(signal.ITIMER_PROF, 0)
        print(response, flush=True)
    except BaseException as error:
        print(json.dumps({'error': type(error).__name__ + ': ' + str(error)}), flush=True)
        sys.exit(2)
