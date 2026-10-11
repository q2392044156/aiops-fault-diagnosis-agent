import sys
import urllib.request


url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        if response.status != 200:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
