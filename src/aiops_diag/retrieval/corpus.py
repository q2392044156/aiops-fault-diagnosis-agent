import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import yaml


REQUIRED_SECTIONS = {"overview", "evidence", "steps", "risk"}
FORBIDDEN = (re.compile(r"blk_-?\d+", re.I), re.compile(r"anomaly_score", re.I),
             re.compile(r"(?:^|\W)(?:normal|anomaly)[_-]?label(?:\W|$)", re.I))


def normalized(text):
    return "\n".join(line.rstrip() for line in unicodedata.normalize("NFKC", text).strip().splitlines())


def load_cards(directory):
    cards = [json.loads(path.read_text(encoding="utf-8"))
             for path in sorted(Path(directory).glob("*.json"))]
    return cards


def load_sources(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["sources"]


def validate_corpus(cfg):
    cards = load_cards(cfg["paths"]["cards_dir"])
    sources = load_sources(cfg["paths"]["sources"])
    if len(cards) != 30:
        raise ValueError(f"Knowledge corpus must contain exactly 30 cards, found {len(cards)}")
    if sum(card.get("category") == "hdfs" for card in cards) != 24:
        raise ValueError("Knowledge corpus must contain exactly 24 HDFS cards")
    if sum(card.get("category") == "operations" for card in cards) != 6:
        raise ValueError("Knowledge corpus must contain exactly 6 operations cards")
    source_map = {item["source_id"]: item for item in sources}
    if len(source_map) != len(sources):
        raise ValueError("Source identifiers must be unique")
    doc_ids = set()
    for card in cards:
        required = {"schema_version", "doc_id", "title", "category", "content_origin",
                    "component", "product", "version_scope", "symptoms", "evidence_required",
                    "risk_level", "source_ids", "maintained_at", "author", "review_status",
                    "sections"}
        missing = required - set(card)
        if missing:
            raise ValueError(f"Card is missing fields: {sorted(missing)}")
        if card["schema_version"] != 1 or card["content_origin"] != "original":
            raise ValueError(f"Card {card['doc_id']} is not an original v1 card")
        if card["doc_id"] in doc_ids or not re.fullmatch(r"[a-z0-9-]{3,64}", card["doc_id"]):
            raise ValueError(f"Invalid or duplicate doc_id: {card['doc_id']}")
        doc_ids.add(card["doc_id"])
        section_ids = {item.get("id") for item in card["sections"]}
        if section_ids != REQUIRED_SECTIONS:
            raise ValueError(f"Card {card['doc_id']} must contain the four required sections")
        if not all(source in source_map for source in card["source_ids"]):
            raise ValueError(f"Card {card['doc_id']} refers to an unknown source")
        payload = json.dumps(card, ensure_ascii=False)
        if any(pattern.search(payload) for pattern in FORBIDDEN):
            raise ValueError(f"Card {card['doc_id']} contains forbidden evaluation data")
    for source in sources:
        url = source.get("source_url")
        if url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"hadoop.apache.org"}:
                raise ValueError(f"Source URL is not allowlisted: {url}")
    return cards, sources


def evidence_units(card):
    return [{"evidence_unit_id": f"{card['doc_id']}:{section['id']}",
             "doc_id": card["doc_id"], "section_id": section["id"],
             "heading": section["heading"], "text": normalized(section["text"])}
            for section in card["sections"]]


def _chunk_id(kb_version, variant, doc_id, section_path, text):
    raw = "|".join((kb_version, variant, doc_id, section_path, normalized(text)))
    return "chk_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _metadata(card, sources):
    source = sources[card["source_ids"][0]]
    return {
        "doc_id": card["doc_id"], "title": card["title"],
        "component": card["component"], "product": card["product"],
        "version_scope": card["version_scope"], "risk_level": card["risk_level"],
        "source_id": source["source_id"], "source_url": source.get("source_url"),
        "source_version": source["source_version"], "maintained_at": card["maintained_at"],
    }


def chunk_structured(cards, sources, kb_version):
    chunks = []
    for card in cards:
        meta = _metadata(card, sources)
        for unit in evidence_units(card):
            text = normalized(f"{card['title']}\n{unit['heading']}\n{unit['text']}")
            chunks.append({**meta, "variant": "structured", "section_path": unit["heading"],
                           "evidence_unit_ids": [unit["evidence_unit_id"]], "text": text,
                           "chunk_id": _chunk_id(kb_version, "structured", card["doc_id"],
                                                 unit["heading"], text)})
    return chunks


def chunk_fixed(cards, sources, kb_version, tokenizer, size=300, overlap=50):
    chunks = []
    for card in cards:
        meta = _metadata(card, sources)
        pieces, spans, position = [card["title"] + "\n"], [], len(card["title"]) + 1
        for unit in evidence_units(card):
            part = f"{unit['heading']}\n{unit['text']}\n"
            start, end = position, position + len(part)
            spans.append((start, end, unit["evidence_unit_id"]))
            pieces.append(part); position = end
        text = normalized("".join(pieces))
        encoding = tokenizer.encode(text, add_special_tokens=False)
        offsets = [(start, end) for start, end in encoding.offsets if end > start]
        if not offsets:
            continue
        step = size - overlap
        for number, begin in enumerate(range(0, len(offsets), step), 1):
            window = offsets[begin:begin + size]
            if not window:
                break
            start_char, end_char = window[0][0], window[-1][1]
            body = normalized(text[start_char:end_char])
            units = [unit_id for start, end, unit_id in spans
                     if start < end_char and end > start_char]
            section = f"fixed-{number}"
            chunks.append({**meta, "variant": "fixed", "section_path": section,
                           "evidence_unit_ids": units, "text": body,
                           "chunk_id": _chunk_id(kb_version, "fixed", card["doc_id"], section, body)})
            if begin + size >= len(offsets):
                break
    return chunks


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                  for row in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
