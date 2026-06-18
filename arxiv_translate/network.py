from __future__ import annotations

import urllib.request
from typing import Any


def urlopen(
    request: str | urllib.request.Request,
    *,
    timeout: int,
    use_proxy: bool,
) -> Any:
    """Open a URL using environment proxies or an explicitly direct connection."""

    if use_proxy:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)
