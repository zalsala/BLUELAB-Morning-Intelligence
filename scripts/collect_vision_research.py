#!/usr/bin/env python3
"""Collect and normalize vision-research candidates from public scholarly APIs.

Live mode uses only Python stdlib. CI should run --self-test, which performs no
network access.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY_FILE = ROOT / "config" / "vision-research-queries.json"
USER_AGENT = "BLUELAB-Morning-Intelligence/1.0 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)"
TIMEOUT = 25


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value):
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_doi(value):
    value = clean_text(value).lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    return value.removeprefix("doi:").strip()


def norm_title(value):
    return re.sub(r"[^a-z0-9가-힣]+", " ", clean_text(value).lower()).strip()


def classify_kind(text):
    t = clean_text(text).lower()
    if "randomized" in t or "randomised" in t or "randomized controlled trial" in t:
        return "RCT"
    if "meta-analysis" in t or "meta analysis" in t:
        return "META-ANALYSIS"
    if "systematic review" in t:
        return "SYSTEMATIC REVIEW"
    if "review" in t:
        return "REVIEW"
    if "guideline" in t or "practice pattern" in t:
        return "GUIDELINE"
    if "preprint" in t:
        return "PREPRINT"
    if any(x in t for x in ("observational", "cohort", "case-control", "cross-sectional")):
        return "OBSERVATIONAL"
    if "clinical trial" in t or "interventional" in t:
        return "CLINICAL TRIAL"
    return "RESEARCH / ISSUE"


def request_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def request_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")


def base_record(source, family, title, url, **extra):
    title = clean_text(title)
    abstract = clean_text(extra.pop("abstract", ""))
    kind_text = " ".join([title, abstract, clean_text(extra.get("study_type", ""))])
    return {
        "collector_source": source,
        "topic_id": family["id"],
        "topic_label": family["label"],
        "title": title,
        "abstract": abstract,
        "journal": clean_text(extra.pop("journal", "")),
        "publication_date": clean_text(extra.pop("publication_date", "")),
        "url": url,
        "doi": norm_doi(extra.pop("doi", "")),
        "pmid": clean_text(extra.pop("pmid", "")),
        "nct_id": clean_text(extra.pop("nct_id", "")),
        "authors": extra.pop("authors", []),
        "evidence_type": classify_kind(kind_text),
        "retrieved_at": now_iso(),
        **extra,
    }


def pubmed(family, days, limit):
    mindate = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    term = f'({family["query"]}) AND ("{mindate}"[Date - Publication] : "3000"[Date - Publication])'
    q = urllib.parse.urlencode({"db":"pubmed","term":term,"retmode":"json","retmax":limit,"sort":"pub date"})
    ids = request_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + q)["esearchresult"]["idlist"]
    if not ids:
        return []
    xml = request_text("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode({"db":"pubmed","id":",".join(ids),"retmode":"xml"}))
    root = ET.fromstring(xml)
    out = []
    for article in root.findall(".//PubmedArticle"):
        med = article.find("MedlineCitation")
        art = med.find("Article") if med is not None else None
        if art is None:
            continue
        pmid = clean_text(med.findtext("PMID"))
        node = art.find("ArticleTitle")
        title = "".join(node.itertext()) if node is not None else ""
        abstract = " ".join("".join(x.itertext()) for x in art.findall("Abstract/AbstractText"))
        journal = art.findtext("Journal/Title") or ""
        pubdate = art.find("Journal/JournalIssue/PubDate")
        parts = []
        if pubdate is not None:
            parts = [clean_text(pubdate.findtext(x)) for x in ("Year","Month","Day") if pubdate.findtext(x)]
        doi = ""
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = aid.text or ""
                break
        authors = []
        for a in art.findall("AuthorList/Author")[:12]:
            name = " ".join(filter(None, [a.findtext("ForeName"), a.findtext("LastName")]))
            if name:
                authors.append(clean_text(name))
        out.append(base_record("pubmed", family, title, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", abstract=abstract, journal=journal, publication_date="-".join(parts), doi=doi, pmid=pmid, authors=authors))
    return out


def europe_pmc(family, days, limit):
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    query = f'({family["query"]}) AND FIRST_PDATE:[{since} TO 3000-12-31]'
    params = urllib.parse.urlencode({"query":query,"format":"json","pageSize":limit,"sort":"FIRST_PDATE_D"})
    data = request_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + params)
    out = []
    for x in data.get("resultList", {}).get("result", []):
        pmid = clean_text(x.get("pmid", ""))
        doi = norm_doi(x.get("doi", ""))
        url = f"https://europepmc.org/article/MED/{pmid}" if pmid else (f"https://doi.org/{doi}" if doi else "https://europepmc.org/")
        out.append(base_record("europe-pmc", family, x.get("title", ""), url, abstract=x.get("abstractText", ""), journal=x.get("journalTitle", ""), publication_date=x.get("firstPublicationDate") or x.get("firstIndexDate", ""), doi=doi, pmid=pmid, authors=clean_text(x.get("authorString", "")).split(", ") if x.get("authorString") else [], study_type=x.get("pubType", ""), external_id=clean_text(x.get("id", ""))))
    return out


def crossref(family, days, limit):
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    params = urllib.parse.urlencode({"query.bibliographic":family["query"],"filter":f"from-pub-date:{since}","rows":limit,"sort":"published","order":"desc","select":"DOI,title,abstract,container-title,published-online,published-print,author,type,URL"})
    data = request_json("https://api.crossref.org/works?" + params)
    out = []
    for x in data.get("message", {}).get("items", []):
        title = (x.get("title") or [""])[0]
        container = (x.get("container-title") or [""])[0]
        parts = ((x.get("published-online") or x.get("published-print") or {}).get("date-parts") or [[]])[0]
        pubdate = "-".join(str(i).zfill(2) if n else str(i) for n, i in enumerate(parts))
        doi = norm_doi(x.get("DOI", ""))
        authors = [" ".join(filter(None, [a.get("given", ""), a.get("family", "")])).strip() for a in x.get("author", [])[:12]]
        out.append(base_record("crossref", family, title, f"https://doi.org/{doi}" if doi else x.get("URL", ""), abstract=x.get("abstract", ""), journal=container, publication_date=pubdate, doi=doi, authors=authors, study_type=x.get("type", "")))
    return out


def clinical_trials(family, days, limit):
    params = urllib.parse.urlencode({"query.term":family["query"],"format":"json","pageSize":limit,"sort":"LastUpdatePostDate:desc"})
    data = request_json("https://clinicaltrials.gov/api/v2/studies?" + params)
    cutoff = dt.date.today() - dt.timedelta(days=days)
    out = []
    for x in data.get("studies", []):
        p = x.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        status = p.get("statusModule", {})
        design = p.get("designModule", {})
        desc = p.get("descriptionModule", {})
        nct = clean_text(ident.get("nctId", ""))
        date_text = status.get("lastUpdatePostDateStruct", {}).get("date", "") or status.get("studyFirstPostDateStruct", {}).get("date", "")
        try:
            if date_text and dt.date.fromisoformat(date_text[:10]) < cutoff:
                continue
        except ValueError:
            pass
        out.append(base_record("clinicaltrials", family, ident.get("briefTitle", ""), f"https://clinicaltrials.gov/study/{nct}", abstract=desc.get("briefSummary", ""), publication_date=date_text, nct_id=nct, study_type=clean_text(design.get("studyType", "")), recruitment_status=clean_text(status.get("overallStatus", "")), enrollment=(design.get("enrollmentInfo") or {}).get("count")))
    return out


PROVIDERS = {"pubmed":pubmed, "europe-pmc":europe_pmc, "crossref":crossref, "clinicaltrials":clinical_trials}


def dedupe(records):
    seen, out = set(), []
    for r in records:
        key = (("doi", r["doi"]) if r.get("doi") else ("pmid", r["pmid"]) if r.get("pmid") else ("nct", r["nct_id"]) if r.get("nct_id") else ("title", norm_title(r.get("title", ""))))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def self_test():
    assert norm_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert norm_title("Binocular-Vision: Study!") == "binocular vision study"
    assert classify_kind("A randomized controlled trial") == "RCT"
    sample = [
        base_record("pubmed", {"id":"x","label":"X"}, "Same paper", "u", doi="10.1/a"),
        base_record("crossref", {"id":"x","label":"X"}, "Same paper", "u2", doi="https://doi.org/10.1/A"),
        base_record("clinicaltrials", {"id":"x","label":"X"}, "Trial", "u3", nct_id="NCT1"),
    ]
    assert len(dedupe(sample)) == 2
    cfg = json.loads(QUERY_FILE.read_text(encoding="utf-8"))
    assert len(cfg["families"]) >= 6
    assert {x["id"] for x in cfg["families"]} >= {"myopia","binocular","contact_cornea","ophthalmology","vision_science","optometry"}
    print("PASS: vision research collector self-test")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("--limit-per-source", type=int, default=12)
    ap.add_argument("--providers", default="pubmed,europe-pmc,crossref,clinicaltrials")
    ap.add_argument("--output", default="artifacts/vision-research-candidates.json")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    cfg = json.loads(QUERY_FILE.read_text(encoding="utf-8"))
    days = args.days or cfg.get("default_window_days", 30)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    unknown = sorted(set(providers) - set(PROVIDERS))
    if unknown:
        raise SystemExit(f"unknown providers: {unknown}")
    records, errors = [], []
    for family in cfg["families"]:
        for provider in providers:
            try:
                records.extend(PROVIDERS[provider](family, days, args.limit_per_source))
            except Exception as exc:
                errors.append({"provider":provider,"topic_id":family["id"],"error":f"{type(exc).__name__}: {exc}"})
    records = dedupe(records)
    payload = {"schema_version":"vision-research-candidates-v1","generated_at":now_iso(),"window_days":days,"providers":providers,"candidate_count":len(records),"errors":errors,"candidates":records}
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out}: {len(records)} deduplicated candidates; {len(errors)} provider/topic errors")
    if not records:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
