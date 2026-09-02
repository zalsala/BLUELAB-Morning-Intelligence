#!/usr/bin/env python3
"""Collect diverse candidate links for the four priority Morning Intelligence chapters.

Public RSS/Atom feeds are preferred. Conservative same-domain HTML discovery is
used for official pages without a reliable feed. The collector never publishes
stories; it only produces a candidate pool for later verification/editorial use.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "priority-news-acquisition.json"
UA = "BLUELAB-Morning-Intelligence/1.0 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)"
TIMEOUT = 20


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def host(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def get(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(), r.headers.get_content_type()


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def feed_entries(root):
    # Covers RSS, RDF/RSS and Atom regardless of XML namespace.
    return [n for n in root.iter() if local(n.tag) in {"item", "entry"}]


def parse_feed(raw, source_cfg, chapter, limit):
    root = ET.fromstring(raw)
    records = []
    for item in feed_entries(root)[:limit]:
        title = ""
        link = ""
        published = ""
        summary = ""
        for child in list(item):
            name = local(child.tag)
            if name == "title" and not title:
                title = clean("".join(child.itertext()))
            elif name == "link" and not link:
                link = clean(child.attrib.get("href") or child.text or "")
            elif name in {"pubdate", "published", "updated", "date", "issued"} and not published:
                published = clean("".join(child.itertext()))
            elif name in {"description", "summary", "content", "encoded"} and not summary:
                summary = clean(re.sub(r"<[^>]+>", " ", "".join(child.itertext())))
        if title and link.startswith("http"):
            records.append({
                "chapter": chapter,
                "collector_id": source_cfg["id"],
                "source": source_cfg["source"],
                "tier": source_cfg["tier"],
                "title": title,
                "url": link,
                "domain": host(link),
                "published": published,
                "summary": summary[:700],
                "acquisition_mode": "feed",
            })
    return records


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, clean(" ".join(self._text))))
            self._href = None
            self._text = []


def same_site(candidate, base):
    a, b = host(candidate), host(base)
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def parse_html(raw, source_cfg, chapter, limit):
    base = source_cfg["url"]
    patterns = source_cfg.get("include", [])
    parser = LinkParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    records, seen = [], set()
    for href, title in parser.links:
        if not href or len(title) < 12:
            continue
        url = urllib.parse.urljoin(base, href)
        if not url.startswith("http") or not same_site(url, base):
            continue
        path = urllib.parse.urlparse(url).path
        if patterns and not any(p in path for p in patterns):
            continue
        key = url.split("#", 1)[0]
        if key in seen or key.rstrip("/") == base.rstrip("/"):
            continue
        seen.add(key)
        records.append({
            "chapter": chapter,
            "collector_id": source_cfg["id"],
            "source": source_cfg["source"],
            "tier": source_cfg["tier"],
            "title": title,
            "url": key,
            "domain": host(key),
            "published": "",
            "summary": "",
            "acquisition_mode": "html",
        })
        if len(records) >= limit:
            break
    return records


def dedupe(records):
    """Deduplicate within a chapter, not globally across chapters.

    The same source article may legitimately be a candidate for both economy and
    stocks; the later chapter-specific selector decides whether it belongs in
    either final section. Global dedup here incorrectly starved later chapters.
    """
    seen_urls, seen_titles, out = set(), set(), []
    for r in records:
        chapter = r.get("chapter", "")
        u = r["url"].rstrip("/")
        t = re.sub(r"[^a-z0-9가-힣]+", " ", r["title"].lower()).strip()
        url_key = (chapter, u)
        title_key = (chapter, t)
        if not u or url_key in seen_urls or (t and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if t:
            seen_titles.add(title_key)
        out.append(r)
    return out


def self_test():
    rss = b'''<rss><channel><item><title>Example market release</title><link>https://example.com/a</link><pubDate>Tue, 01 Sep 2026 00:00:00 GMT</pubDate></item></channel></rss>'''
    cfg = {"id":"x","source":"Example","tier":1}
    got = parse_feed(rss, cfg, "경제 · 시장", 10)
    assert len(got) == 1 and got[0]["domain"] == "example.com"

    rdf = b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"><item><title>Namespaced science item</title><link>https://science.example.org/paper</link></item></rdf:RDF>'''
    got_rdf = parse_feed(rdf, cfg, "과학", 10)
    assert len(got_rdf) == 1 and got_rdf[0]["domain"] == "science.example.org"

    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom science item</title><link href="https://atom.example.org/paper"/><updated>2026-09-02T00:00:00Z</updated></entry></feed>'''
    got_atom = parse_feed(atom, cfg, "과학", 10)
    assert len(got_atom) == 1 and got_atom[0]["url"] == "https://atom.example.org/paper"

    html_raw = b'<html><a href="/news/2026/story-one">A sufficiently descriptive science story title</a></html>'
    cfg2 = {"id":"y","source":"Example","tier":0,"url":"https://example.org/news","include":["/news/"]}
    got2 = parse_html(html_raw, cfg2, "과학", 10)
    assert len(got2) == 1 and got2[0]["url"] == "https://example.org/news/2026/story-one"

    # Same URL is one candidate inside a chapter, but may remain a candidate in
    # a second chapter for later semantic classification.
    same_econ = dict(got[0])
    same_stock = dict(got[0], chapter="국내·해외 주식 · 이슈기업")
    assert len(dedupe(got + got)) == 1
    assert len(dedupe([same_econ, same_stock])) == 2

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert len(config["chapters"]) == 4
    assert all(len(v) >= 5 for v in config["chapters"].values())
    print("PASS: priority-news collector self-test")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--limit-per-source", type=int, default=10)
    ap.add_argument("--output", default="artifacts/priority-news-candidates.json")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    records, errors, source_status = [], [], []
    for chapter, sources in cfg["chapters"].items():
        for source in sources:
            try:
                raw, content_type = get(source["url"])
                if source["mode"] == "feed":
                    found = parse_feed(raw, source, chapter, args.limit_per_source)
                elif source["mode"] == "html":
                    found = parse_html(raw, source, chapter, args.limit_per_source)
                else:
                    raise ValueError(f"unsupported mode {source['mode']}")
                records.extend(found)
                source_status.append({"chapter":chapter,"id":source["id"],"status":"PASS","count":len(found),"content_type":content_type})
            except Exception as exc:
                errors.append({"chapter":chapter,"id":source["id"],"url":source["url"],"error":f"{type(exc).__name__}: {exc}"})
                source_status.append({"chapter":chapter,"id":source["id"],"status":"ERROR","count":0})

    records = dedupe(records)
    by_chapter = defaultdict(list)
    for r in records:
        by_chapter[r["chapter"]].append(r)

    chapter_report = {}
    for chapter in cfg["chapters"]:
        items = by_chapter.get(chapter, [])
        domains = Counter(r["domain"] for r in items if r["domain"])
        chapter_report[chapter] = {
            "candidate_count": len(items),
            "unique_domains": len(domains),
            "domain_counts": dict(domains),
            "candidate_target_met": len(items) >= cfg.get("candidate_target_per_chapter", 30),
            "domain_target_met": len(domains) >= cfg.get("minimum_unique_domains_for_candidate_pool", 5),
        }

    payload = {
        "schema_version":"priority-news-candidates-v2",
        "generated_at":now_iso(),
        "candidate_count":len(records),
        "error_count":len(errors),
        "source_status":source_status,
        "errors":errors,
        "chapter_report":chapter_report,
        "candidates":records,
    }
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out}: {len(records)} candidates; {len(errors)} source errors")
    for chapter, report in chapter_report.items():
        print(f"  {chapter}: {report['candidate_count']} candidates / {report['unique_domains']} domains / candidate_target={report['candidate_target_met']} / domain_target={report['domain_target_met']}")
    for error in errors[:12]:
        print("  ERROR", error)
    if not records:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
