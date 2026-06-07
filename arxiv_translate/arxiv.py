from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .errors import InvalidArxivLinkError, SourceUnavailableError


NEW_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)")
OLD_ID_RE = re.compile(
    r"(?P<id>(?:[a-z-]+(?:\.[A-Z]{2})?)/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)


def parse_arxiv_id(value: str) -> str:
    """Extract an arXiv identifier from a raw ID or arxiv.org URL."""

    value = value.strip()
    if not value:
        raise InvalidArxivLinkError("empty arXiv link")

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        if host not in {"arxiv.org", "www.arxiv.org"}:
            raise InvalidArxivLinkError(f"not an arxiv.org URL: {value}")
        path = parsed.path.strip("/")
        parts = path.split("/")
        if not parts:
            raise InvalidArxivLinkError(f"missing arXiv id in URL: {value}")

        if parts[0] in {"abs", "pdf", "html", "format"}:
            candidate = "/".join(parts[1:])
        else:
            candidate = path
    else:
        candidate = value

    candidate = candidate.removesuffix(".pdf")
    candidate = candidate.removesuffix(".html")
    candidate = candidate.strip("/")

    match = NEW_ID_RE.search(candidate)
    if match:
        return match.group("id")

    match = OLD_ID_RE.search(candidate)
    if match:
        return match.group("id")

    raise InvalidArxivLinkError(f"could not parse arXiv id from: {value}")


def eprint_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/e-print/{arxiv_id}"


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def download_pdf(arxiv_id: str, destination: Path, timeout: int = 60) -> Path:
    """Download the original arXiv PDF."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        pdf_url(arxiv_id),
        headers={
            "User-Agent": "arxiv-translate/0.1 (https://arxiv.org; mailto:none)",
            "Accept": "application/pdf,*/*",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise SourceUnavailableError(
            f"failed to download arXiv PDF for {arxiv_id}: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SourceUnavailableError(
            f"failed to download arXiv PDF for {arxiv_id}: {exc.reason}"
        ) from exc

    if not body:
        raise SourceUnavailableError(f"arXiv returned an empty PDF for {arxiv_id}")
    if not body.startswith(b"%PDF") and "pdf" not in content_type.lower():
        raise SourceUnavailableError(f"arXiv did not return a PDF for {arxiv_id}")

    destination.write_bytes(body)
    return destination


def download_source(arxiv_id: str, destination: Path, timeout: int = 60) -> Path:
    """Download the arXiv e-print source archive."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        eprint_url(arxiv_id),
        headers={
            "User-Agent": "arxiv-translate/0.1 (https://arxiv.org; mailto:none)",
            "Accept": "application/octet-stream,*/*",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 404, 410}:
            raise SourceUnavailableError(
                f"arXiv source is unavailable for {arxiv_id} (HTTP {exc.code})"
            ) from exc
        raise SourceUnavailableError(
            f"failed to download arXiv source for {arxiv_id}: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SourceUnavailableError(
            f"failed to download arXiv source for {arxiv_id}: {exc.reason}"
        ) from exc

    if not body:
        raise SourceUnavailableError(f"arXiv returned an empty source for {arxiv_id}")
    if body.startswith(b"%PDF"):
        raise SourceUnavailableError(
            f"arXiv did not provide TeX source for {arxiv_id}; e-print is a PDF"
        )
    if "text/html" in content_type.lower() and b"<html" in body[:512].lower():
        raise SourceUnavailableError(
            f"arXiv did not provide a downloadable TeX source for {arxiv_id}"
        )

    destination.write_bytes(body)
    return destination
