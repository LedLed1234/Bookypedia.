import os
import re
from difflib import SequenceMatcher

from flask import current_app

from .base import BookProvider, ProviderUnavailable
from .google_books import GoogleBooksProvider
from .open_library import OpenLibraryProvider


KNOWN_PROVIDERS = {"open_library", "google_books"}


def create_provider(configured="open_library"):
    if configured == "open_library":
        return OpenLibraryProvider()
    if configured == "google_books":
        return GoogleBooksProvider(api_key=os.environ.get("GOOGLE_BOOKS_API_KEY"))
    raise RuntimeError(f"Unbekannter Buchanbieter: {configured}")


class PrimaryFallbackProvider(BookProvider):
    """Use the fallback only when the primary has no plausible result."""

    def __init__(self, primary_name, fallback_name=None):
        self.primary_name = primary_name
        self.fallback_name = fallback_name if fallback_name != primary_name else None
        self.cache_identity = f"primary_fallback:{primary_name}:{self.fallback_name or '-'}"
        self.primary = create_provider(primary_name)
        self.fallback = create_provider(self.fallback_name) if self.fallback_name else None

    def search(self, query, limit=12):
        return self._query("search", query, limit)

    def suggest(self, query, limit=6):
        return self._query("suggest", query, limit)

    def _query(self, method, query, limit):
        primary_error = None
        try:
            primary_results = getattr(self.primary, method)(query, limit=limit)
        except ProviderUnavailable as error:
            primary_error = error
            primary_results = []
        if _has_good_result(query, primary_results) or not self.fallback:
            if primary_error:
                raise primary_error
            return primary_results
        try:
            fallback_results = getattr(self.fallback, method)(query, limit=limit)
        except ProviderUnavailable:
            if primary_results:
                return primary_results
            if primary_error:
                raise primary_error
            raise
        if _has_good_result(query, fallback_results):
            return fallback_results
        return primary_results or fallback_results


def get_provider(configured=None):
    if configured:
        return create_provider(configured)
    primary = current_app.config.get("BOOK_PROVIDER", "open_library")
    fallback = current_app.config.get("BOOK_FALLBACK_PROVIDER")
    return PrimaryFallbackProvider(primary, fallback)


def _has_good_result(query, results):
    normalized_query = _normalize(query)
    if not normalized_query or not results:
        return False
    for book in results:
        authors = book.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        for value in (book.get("title"), book.get("isbn"), *authors):
            candidate = _normalize(value)
            if not candidate:
                continue
            if candidate == normalized_query or candidate.startswith(normalized_query):
                return True
            query_words = normalized_query.split()
            candidate_words = candidate.split()
            if query_words and all(
                any(word.startswith(query_word) for word in candidate_words)
                for query_word in query_words
            ):
                return True
            if len(normalized_query) >= 5 and SequenceMatcher(
                None, normalized_query, candidate
            ).ratio() >= 0.82:
                return True
    return False


def _normalize(value):
    return " ".join(re.findall(r"\w+", str(value or "").casefold(), flags=re.UNICODE))

