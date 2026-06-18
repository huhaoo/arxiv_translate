from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from xml.etree import ElementTree

from .errors import ArxivTranslateError
from .network import urlopen

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_BIBTEX_URL = "https://arxiv.org/bibtex"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_NS = {"arxiv": "http://arxiv.org/schemas/atom"}
BIBTEX_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


@dataclass(frozen=True)
class ArxivMetadata:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    primary_category: str | None = None
    doi: str | None = None
    journal_ref: str | None = None
    comment: str | None = None
    citation_key: str | None = None

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"

    @property
    def year(self) -> str:
        return self.published[:4]


def fetch_arxiv_metadata(
    arxiv_id: str,
    timeout: int = 30,
    *,
    use_proxy: bool = True,
) -> ArxivMetadata:
    query = urllib.parse.urlencode({"id_list": arxiv_id})
    request = urllib.request.Request(
        f"{ARXIV_API_URL}?{query}",
        headers={"User-Agent": "arxiv-translate/0.1 (https://arxiv.org; mailto:none)"},
    )

    try:
        with urlopen(request, timeout=timeout, use_proxy=use_proxy) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ArxivTranslateError(
            f"failed to fetch arXiv metadata for {arxiv_id}: HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        raise ArxivTranslateError(
            f"failed to fetch arXiv metadata for {arxiv_id}: {reason}"
        ) from exc

    metadata = parse_arxiv_metadata(body, arxiv_id)
    return replace(
        metadata,
        citation_key=fetch_arxiv_bibtex_key(
            arxiv_id,
            timeout=timeout,
            use_proxy=use_proxy,
        ),
    )


def fetch_arxiv_bibtex_key(
    arxiv_id: str,
    timeout: int = 30,
    *,
    use_proxy: bool = True,
) -> str:
    encoded_id = urllib.parse.quote(arxiv_id, safe="/")
    request = urllib.request.Request(
        f"{ARXIV_BIBTEX_URL}/{encoded_id}",
        headers={"User-Agent": "arxiv-translate/0.1 (https://arxiv.org; mailto:none)"},
    )

    try:
        with urlopen(request, timeout=timeout, use_proxy=use_proxy) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ArxivTranslateError(
            f"failed to fetch arXiv BibTeX citation for {arxiv_id}: HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        raise ArxivTranslateError(
            f"failed to fetch arXiv BibTeX citation for {arxiv_id}: {reason}"
        ) from exc

    return parse_bibtex_key(body.decode("utf-8", errors="replace"), arxiv_id)


def parse_bibtex_key(bibtex: str, arxiv_id: str) -> str:
    match = BIBTEX_KEY_RE.search(bibtex)
    if not match:
        raise ArxivTranslateError(f"arXiv BibTeX citation key not found for {arxiv_id}")
    return match.group(1)


def parse_arxiv_metadata(body: bytes, arxiv_id: str) -> ArxivMetadata:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ArxivTranslateError("arXiv metadata response is not valid XML") from exc

    entry = root.find("atom:entry", ATOM_NS)
    if entry is None:
        raise ArxivTranslateError(f"arXiv metadata not found for {arxiv_id}")

    categories = [
        category.attrib["term"]
        for category in entry.findall("atom:category", ATOM_NS)
        if category.attrib.get("term")
    ]
    primary = entry.find("arxiv:primary_category", {**ATOM_NS, **ARXIV_NS})

    return ArxivMetadata(
        arxiv_id=arxiv_id,
        title=_entry_text(entry, "atom:title"),
        authors=[
            _normalize(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
            if _normalize(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        ],
        abstract=_entry_text(entry, "atom:summary"),
        published=_entry_text(entry, "atom:published"),
        updated=_entry_text(entry, "atom:updated"),
        categories=categories,
        primary_category=primary.attrib.get("term") if primary is not None else None,
        doi=_optional_arxiv_text(entry, "doi"),
        journal_ref=_optional_arxiv_text(entry, "journal_ref"),
        comment=_optional_arxiv_text(entry, "comment"),
    )


def _entry_text(entry: ElementTree.Element, tag: str) -> str:
    return _normalize(entry.findtext(tag, default="", namespaces=ATOM_NS))


def _optional_arxiv_text(entry: ElementTree.Element, tag: str) -> str | None:
    value = entry.findtext(f"arxiv:{tag}", default="", namespaces={**ATOM_NS, **ARXIV_NS})
    value = _normalize(value)
    return value or None


def _normalize(value: str) -> str:
    return " ".join(value.split())
