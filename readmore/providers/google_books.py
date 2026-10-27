import re

import requests

from .base import BookProvider, ProviderUnavailable


class GoogleBooksProvider(BookProvider):
    API_URL = "https://www.googleapis.com/books/v1/volumes"
    REQUEST_HEADERS = {"User-Agent": "Epiloguehouse/1.0 (personal reading manager)"}

    def __init__(self, api_key=None):
        self.api_key = str(api_key or "").strip() or None

    def search(self, query, limit=12):
        params = {
            "q": query,
            "maxResults": min(40, max(1, int(limit))),
            "printType": "books",
            "projection": "full",
        }
        if self.api_key:
            params["key"] = self.api_key
        payload = self._get_json(self.API_URL, params=params)
        books = [self._normalize_volume(item) for item in payload.get("items", [])]
        return [book for book in books if book][:limit]

    def metadata(self, provider_book_id, provider_edition_id=None):
        volume_id = str(provider_edition_id or provider_book_id or "").strip()
        if not volume_id:
            return {}
        params = {"projection": "full"}
        if self.api_key:
            params["key"] = self.api_key
        volume = self._get_json(f"{self.API_URL}/{volume_id}", params=params)
        book = self._normalize_volume(volume)
        if not book:
            return {}
        return {
            key: book.get(key)
            for key in (
                "provider_edition_id", "isbn", "publisher", "publish_date",
                "page_count", "language", "description", "physical_format",
                "subtitle", "subjects",
            )
            if book.get(key) not in (None, "", [])
        }

    def _get_json(self, url, params=None):
        try:
            response = requests.get(
                url, params=params, timeout=(3.05, 8), headers=self.REQUEST_HEADERS
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Google Books hat keine gültige JSON-Antwort geliefert.")
            return payload
        except (requests.RequestException, ValueError) as error:
            raise ProviderUnavailable("Google Books ist derzeit nicht erreichbar.") from error

    @staticmethod
    def _normalize_volume(item):
        if not isinstance(item, dict):
            return None
        volume_id = str(item.get("id") or "").strip()
        info = item.get("volumeInfo") or {}
        title = str(info.get("title") or "").strip()
        if not volume_id or not title or not isinstance(info, dict):
            return None
        authors = [str(author).strip() for author in info.get("authors", []) if str(author).strip()][:6]
        identifiers = info.get("industryIdentifiers") or []
        isbn = _best_isbn(
            entry.get("identifier") for entry in identifiers if isinstance(entry, dict)
        )
        images = info.get("imageLinks") or {}
        cover_url = images.get("thumbnail") or images.get("smallThumbnail")
        if cover_url:
            cover_url = str(cover_url).replace("http://", "https://", 1)
        publish_date = str(info.get("publishedDate") or "").strip() or None
        year_match = re.search(r"\b(\d{4})\b", publish_date or "")
        return {
            "provider": "google_books",
            "provider_book_id": volume_id,
            "provider_edition_id": volume_id,
            "title": title,
            "subtitle": str(info.get("subtitle") or "").strip() or None,
            "original_title": None,
            "authors": authors,
            "original_authors": [],
            "isbn": isbn,
            "cover_url": cover_url,
            "language": str(info.get("language") or "").strip() or None,
            "first_publish_year": int(year_match.group(1)) if year_match else None,
            "page_count": _positive_int(info.get("pageCount")),
            "publisher": str(info.get("publisher") or "").strip() or None,
            "publish_date": publish_date,
            "description": str(info.get("description") or "").strip() or None,
            "physical_format": "E-Book" if item.get("saleInfo", {}).get("isEbook") else None,
            "subjects": [str(category).strip() for category in info.get("categories", []) if str(category).strip()][:10],
        }


def _best_isbn(values):
    normalized = [
        "".join(character for character in str(value).upper() if character.isdigit() or character == "X")
        for value in values if value
    ]
    return next((value for value in normalized if len(value) == 13), None) or next(
        (value for value in normalized if len(value) == 10), None
    )


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
