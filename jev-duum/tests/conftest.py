"""Keep the test suite out of the audit database.

Every ``JevClient`` writes its request/response to the jev-log API unless
logging is disabled, and unit tests answer with fake openers.  Set
``JEV_NO_LOG`` for the whole suite; tests that exercise the logger build their
own ``JevCallLogger(enabled=True)`` with an injected opener.
"""

import os

os.environ.setdefault("JEV_NO_LOG", "1")
