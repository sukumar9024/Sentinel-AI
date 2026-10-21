import hashlib
import hmac
import secrets
from collections import OrderedDict
from time import monotonic
from threading import Lock


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def verify(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


class RateLimiter:
    """Single API replica limiter. Use shared state before scaling replicas."""

    def __init__(self):
        self.buckets = OrderedDict()
        self.lock = Lock()

    def allow(self, key, limit, seconds=60):
        with self.lock:
            current = monotonic()
            hits = [t for t in self.buckets.pop(key, []) if current - t < seconds]
            allowed = len(hits) < limit
            if allowed:
                hits.append(current)
            self.buckets[key] = hits
            if len(self.buckets) > 10000:
                self.buckets.popitem(last=False)
            return allowed


class RateLimitUnavailable(Exception):
    pass


class SharedRateLimiter:
    """Atomic fixed windows shared across API replicas. No fallback that bypasses limits."""

    def __init__(self, url):
        from redis import Redis

        self.redis = Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def allow(self, key, limit, seconds=60):
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        try:
            count = self.redis.eval(
                script, 1, "sentinel:rate:" + hashlib.sha256(key.encode()).hexdigest(), seconds
            )
            return count <= limit
        except Exception as error:
            raise RateLimitUnavailable() from error
