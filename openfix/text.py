"""Chinese-friendly tokenization and BM25 retrieval without external packages."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


CODE_PATTERN = re.compile(r"[a-z]{1,8}-?\d{2,5}", re.IGNORECASE)
LATIN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]+")

STOP_BIGRAMS = {
    "怎么", "如何", "什么", "可以", "需要", "现在", "这个", "那个", "一下",
    "是否", "应该", "要求", "出现", "发生", "进行", "怎么",
}


def tokenize(value: str) -> list[str]:
    """Return normalized technical codes and CJK unigram/bigram tokens.

    Bigrams provide decent Chinese matching without a dictionary dependency.
    Equipment and alarm codes are preserved as high-signal tokens.
    """

    text = (value or "").lower().strip()
    tokens: list[str] = []

    for match in CODE_PATTERN.findall(text):
        compact = match.replace("-", "")
        tokens.extend((match, compact))

    for match in LATIN_PATTERN.findall(text):
        if any(ch.isalpha() for ch in match):
            tokens.append(match)
        if "-" in match:
            tokens.append(match.replace("-", ""))

    for sequence in CJK_PATTERN.findall(text):
        if len(sequence) == 1:
            tokens.append(sequence)
            continue
        tokens.extend(sequence)
        for size in (2, 3):
            for index in range(len(sequence) - size + 1):
                gram = sequence[index : index + size]
                if gram not in STOP_BIGRAMS:
                    tokens.append(gram)

    return tokens


@dataclass(frozen=True)
class SearchDocument:
    id: str
    text: str
    metadata: dict


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    metadata: dict


class BM25Index:
    """Small dependency-free BM25 index suitable for offline edge deployment."""

    def __init__(self, documents: Iterable[SearchDocument], k1: float = 1.45, b: float = 0.72):
        self.documents = list(documents)
        self.k1 = k1
        self.b = b
        self.term_frequencies = [Counter(tokenize(item.text)) for item in self.documents]
        self.lengths = [sum(counts.values()) for counts in self.term_frequencies]
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        document_frequency: Counter[str] = Counter()
        for counts in self.term_frequencies:
            document_frequency.update(counts.keys())
        count = len(self.documents)
        self.idf = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        query_terms = Counter(tokenize(query))
        if not query_terms or not self.documents:
            return []

        hits: list[SearchHit] = []
        for document, frequencies, length in zip(
            self.documents, self.term_frequencies, self.lengths, strict=True
        ):
            score = 0.0
            for term, query_frequency in query_terms.items():
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                numerator = frequency * (self.k1 + 1)
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / (self.average_length or 1.0)
                )
                score += self.idf.get(term, 0.0) * numerator / denominator * query_frequency
            if score > 0:
                hits.append(SearchHit(document.id, score, document.metadata))

        hits.sort(key=lambda item: (-item.score, item.id))
        return hits[:limit]


def extract_known_codes(query: str, known_codes: Iterable[str]) -> set[str]:
    """Extract alarm/equipment codes found in a query."""

    upper_query = (query or "").upper()
    matches: set[str] = set()
    for code in known_codes:
        normalized = (code or "").upper()
        if not normalized:
            continue
        pattern = re.escape(normalized).replace(r"\-", "-?")
        if re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", upper_query):
            matches.add(normalized)
    return matches


def safe_excerpt(value: str, limit: int = 180) -> str:
    """Return a compact excerpt without cutting off the final punctuation carelessly."""

    text = re.sub(r"\s+", " ", (value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，。；、 ") + "…"
