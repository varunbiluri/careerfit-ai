"""
Single slowapi Limiter instance shared across all routers.

Import this in both main.py AND in each router that applies @limiter.limit().
Using a single instance is required: slowapi registers the same Limiter on
app.state.limiter, and @limiter.limit decorators that reference a different
instance will not have access to the app's error handler (→ silent 500 instead
of 429 responses).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
