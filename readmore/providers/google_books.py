import re

import requests

from .base import BookProvider, ProviderUnavailable


class GoogleBooksProvider(BookProvider):
    API_URL = "https://www.googleapis.com/books/v1/volumes"
    REQUEST_HEADERS = {"User-Agent": "Epiloguehouse/1.0 (personal reading manager)"}

    def __init__(self, api_key=None):
        self.api_key = str(api_key or "").strip() or None

    def search(self, query, limit=12):
        return self._search_volumes(query, limit)

    def _search_volumes(self, query, limit=12):
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

    def series(self, provider_book_id, authors=None, limit=24):
        volume_id = str(provider_book_id or "").strip()
        if not volume_id:
            return None
        params = {"projection": "full"}
        if self.api_key:
            params["key"] = self.api_key
        current = self._normalize_volume(
            self._get_json(f"{self.API_URL}/{volume_id}", params=params)
        )
        if not current or not current.get("series_name"):
            return None

        series_name = current["series_name"]
        current_authors = current.get("authors") or list(authors or [])
        query = f'intitle:"{_escape_query_value(series_name)}"'
        if current_authors:
            query += f' inauthor:"{_escape_query_value(current_authors[0])}"'
        request_limit = min(40, max(limit * 2, 12))
        # Autorennamen sind bei Google Books nicht konsistent normalisiert
        # (z. B. Young-do Lee / Yeong do I). Deshalb ergänzt eine breitere
        # Volltextsuche die präzise Titel+Autor-Suche immer. Erst die lokale
        # Reihenprüfung entscheidet, welche Treffer wirklich dazugehören.
        candidates = [
            *self._search_volumes(query, request_limit),
            *self._search_volumes(
                _escape_query_value(series_name), request_limit
            ),
        ]

        matching = []
        for book in [current, *candidates]:
            if not book:
                continue
            same_volume = book["provider_book_id"] == current["provider_book_id"]
            same_series_id = (
                current.get("provider_series_id")
                and book.get("provider_series_id") == current["provider_series_id"]
            )
            same_inferred_series = (
                _normalize_text(book.get("series_name")) == _normalize_text(series_name)
                and (
                    book.get("series_position") is not None
                    or _authors_match(current_authors, book.get("authors") or [])
                )
            )
            if same_volume or same_series_id or same_inferred_series:
                matching.append(book)

        books = _best_series_editions(matching, current, limit)
        if not books:
            return None
        return {
            "name": series_name,
            "provider_series_id": current.get("provider_series_id"),
            "current_position": current.get("series_position"),
            "source": "google_structured"
            if current.get("provider_series_id")
            else "google_title",
            # Google bietet keinen Endpunkt, der eine Reihe vollständig anhand
            # der seriesId auflistet. Die ergänzende Titelsuche kann daher
            # einzelne Ausgaben übersehen.
            "incomplete": True,
            "books": books,
        }

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
        series_name, series_id, series_position = _series_details(info)
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
            "provider_series_id": series_id,
            "series_name": series_name,
            "series_position": series_position,
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


def _series_details(info):
    raw = info.get("seriesInfo") or {}
    volume_series = raw.get("volumeSeries") or [] if isinstance(raw, dict) else []
    relationship = next(
        (entry for entry in volume_series if isinstance(entry, dict)),
        {},
    )
    series_id = str(relationship.get("seriesId") or "").strip() or None
    structured_position = _series_position(
        relationship.get("orderNumber") or raw.get("bookDisplayNumber")
        if isinstance(raw, dict)
        else None
    )
    short_title = str(raw.get("shortSeriesBookTitle") or "").strip() if isinstance(raw, dict) else ""
    series_name, inferred_position = _infer_series_label(
        info.get("title"), info.get("subtitle"), short_title
    )
    return series_name, series_id, structured_position or inferred_position


def _infer_series_label(title, subtitle=None, short_title=None):
    title = str(title or "").strip()
    subtitle = str(subtitle or "").strip()
    short_title = str(short_title or "").strip()

    for value in (subtitle,):
        parsed = _parse_series_label(value, allow_bare_number=True)
        if parsed:
            return parsed

    if short_title and _normalize_text(short_title) != _normalize_text(title):
        remaining = re.sub(re.escape(short_title), "", title, count=1, flags=re.IGNORECASE)
        remaining = remaining.strip(" \t-–—:,.()[]")
        parsed = _parse_series_label(remaining, allow_bare_number=True)
        if parsed:
            return parsed
        if remaining and len(remaining.split()) >= 2:
            return remaining, None

    prefix = re.match(
        r"^(.+?)\s+(?:Band|Bd\.?|Buch|Book|Teil|Vol(?:ume)?\.?)?\s*(\d+(?:\.\d+)?)\s*[-–—:]\s*.+$",
        title,
        flags=re.IGNORECASE,
    )
    if prefix:
        return prefix.group(1).strip(" -–—:,"), _series_position(prefix.group(2))

    parts = re.split(r"\s+[-–—]\s+", title)
    for part in reversed(parts[1:]):
        parsed = _parse_series_label(part, allow_bare_number=True)
        if parsed:
            return parsed

    return _parse_series_label(title, allow_bare_number=False) or (None, None)


def _parse_series_label(value, allow_bare_number=False):
    value = str(value or "").strip().strip("()[]")
    if not value:
        return None
    explicit = re.match(
        r"^(.+?)(?:\s*[-–—,:]\s*)?(?:Band|Bd\.?|Buch|Book|Teil|Vol(?:ume)?\.?)\s*(\d+(?:\.\d+)?)$",
        value,
        flags=re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1).strip(" -–—:,"), _series_position(explicit.group(2))
    if allow_bare_number:
        bare = re.match(r"^(.{4,}?)\s+(\d+(?:\.\d+)?)$", value)
        if bare:
            return bare.group(1).strip(" -–—:,"), _series_position(bare.group(2))
    return None


def _series_position(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip() or None
    return int(number) if number.is_integer() else number


def _authors_match(left, right):
    if not left or not right:
        return True
    left_names = [_normalize_text(author) for author in left if _normalize_text(author)]
    right_names = [_normalize_text(author) for author in right if _normalize_text(author)]
    return any(
        left_name == right_name or left_name in right_name or right_name in left_name
        for left_name in left_names
        for right_name in right_names
    )


def _best_series_editions(books, current, limit):
    by_position = {}
    for book in books:
        book_id = book.get("provider_book_id")
        if not book_id:
            continue
        position = book.get("series_position")
        position_key = f"position:{position}" if position is not None else f"id:{book_id}"
        previous = by_position.get(position_key)
        if previous is None or _edition_score(book, current) > _edition_score(previous, current):
            by_position[position_key] = book
    if current.get("provider_book_id"):
        current_position = current.get("series_position")
        key = (
            f"position:{current_position}"
            if current_position is not None
            else f"id:{current['provider_book_id']}"
        )
        by_position[key] = current
    selected = list(by_position.values())
    selected.sort(key=_series_sort_key)
    return selected[:limit]


def _edition_score(book, current):
    return (
        100 if book.get("provider_book_id") == current.get("provider_book_id") else 0,
        8 if book.get("language") == current.get("language") else 0,
        4 if book.get("cover_url") else 0,
        2 if book.get("page_count") else 0,
        1 if book.get("isbn") else 0,
    )


def _series_sort_key(book):
    position = book.get("series_position")
    try:
        numeric_position = float(position)
    except (TypeError, ValueError):
        numeric_position = float("inf")
    return (
        numeric_position,
        book.get("first_publish_year") is None,
        book.get("first_publish_year") or 0,
        _normalize_text(book.get("title")),
    )


def _normalize_text(value):
    return " ".join(re.findall(r"\w+", str(value or "").casefold(), flags=re.UNICODE))


def _escape_query_value(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')
