import re
from difflib import SequenceMatcher

import requests

from .base import BookProvider, ProviderUnavailable


class OpenLibraryProvider(BookProvider):
    SEARCH_URL = "https://openlibrary.org/search.json"
    API_URL = "https://openlibrary.org"
    BOOKS_API_URL = "https://openlibrary.org/api/books"
    REQUEST_HEADERS = {"User-Agent": "Bookypedia/1.0 (personal local reading manager)"}
    SEARCH_TIMEOUTS = ((3.05, 8), (2, 4))

    def search(self, query, limit=12):
        results = self._request(query, limit)
        # Open Library liefert für unvollständige Titel häufig beliebige
        # Volltexttreffer, obwohl eine Präfixsuche den offensichtlichen Titel
        # findet (z. B. "golden so" -> "Golden Son"). Nur wirklich nahe
        # Direkttreffer dürfen deshalb den toleranten Fallback überspringen.
        if any(_book_match_score(query, book) >= 2.5 for book in results):
            return _closest_results(query, results, limit)
        try:
            fallback = self._request(_tolerant_prefix_query(query), max(12, limit * 3))
        except ProviderUnavailable:
            if results:
                return _closest_results(query, results, limit)
            raise
        merged = _deduplicate_books([*fallback, *results])
        return _closest_results(query, merged, limit)

    def suggest(self, query, limit=6):
        # Eine direkte Relevanzsuche verhindert, dass vollständige Titel wie
        # "Babel" durch einen zu breiten Präfix ("bab*") von Baby-/Baba-
        # Treffern verdrängt werden. Der tolerante Präfix bleibt als Fallback
        # für unvollständige Eingaben und kleine Tippfehler erhalten.
        request_limit = max(12, limit * 2)
        direct = self._request(query, request_limit, retry=False)
        if any(_book_match_score(query, book) >= 2.5 for book in direct):
            return _closest_results(query, direct, limit)
        fallback = self._request(
            _tolerant_prefix_query(query), request_limit, retry=False
        )
        return _closest_results(query, _deduplicate_books([*fallback, *direct]), limit)

    def _request(self, query, limit, *, retry=True):
        params = {
            "q": query,
            "limit": limit,
            "fields": (
                "key,title,author_name,author_alternative_name,isbn,cover_i,"
                "first_publish_year,number_of_pages_median,editions,"
                "editions.key,editions.title,editions.number_of_pages,"
                "editions.author_name,editions.isbn,editions.cover_i,"
                "editions.language,editions.publisher,editions.publish_date,"
                "editions.physical_format"
            ),
        }
        payload = None
        last_error = None
        timeouts = self.SEARCH_TIMEOUTS if retry else self.SEARCH_TIMEOUTS[:1]
        for attempt, timeout in enumerate(timeouts):
            try:
                response = requests.get(
                    self.SEARCH_URL,
                    params=params,
                    timeout=timeout,
                    headers=self.REQUEST_HEADERS,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Open Library hat keine gültige JSON-Antwort geliefert.")
                break
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt + 1 >= len(timeouts) or not _retryable_search_error(error):
                    raise ProviderUnavailable("Open Library ist derzeit nicht erreichbar.") from error
        if payload is None:
            raise ProviderUnavailable("Open Library ist derzeit nicht erreichbar.") from last_error

        books = []
        for item in payload.get("docs", []):
            edition = _matching_edition(item)
            original_title = str(item.get("title") or "").strip()
            title = str(edition.get("title") or original_title).strip()
            if not title:
                continue
            original_authors = [
                str(author).strip() for author in item.get("author_name", []) if str(author).strip()
            ][:4]
            authors = _display_authors(
                edition.get("author_name") or original_authors,
                item.get("author_alternative_name") or [],
            )
            if _is_latin_translation(original_title, title):
                # Open Library führt Übersetzende bei einigen Werken als Autoren.
                # Bei einem klar übersetzten Titel bleibt die erste Person die
                # sichtbare Hauptautorin; die Rohdaten bleiben in original_authors erhalten.
                authors = authors[:1]
            edition_key = _normalize_edition_key(edition.get("key"))
            books.append(
                {
                    "provider": "open_library",
                    "provider_book_id": _normalize_work_key(item.get("key")),
                    "provider_edition_id": edition_key,
                    "title": title,
                    "original_title": original_title if original_title != title else None,
                    "authors": authors,
                    "original_authors": original_authors if original_authors != authors else [],
                    "isbn": _best_isbn(edition.get("isbn", []) or item.get("isbn", [])),
                    "cover_url": _cover_url(edition) or _cover_url(item),
                    "language": _edition_language(edition.get("language")),
                    "first_publish_year": item.get("first_publish_year"),
                    "page_count": _page_count(edition.get("number_of_pages"))
                    or _page_count(item.get("number_of_pages_median")),
                    "publisher": _first_text(edition.get("publisher")),
                    "publish_date": _first_text(edition.get("publish_date")),
                    "physical_format": _first_text(edition.get("physical_format")),
                }
            )
        return _rank_books(books)

    def metadata(self, provider_book_id, provider_edition_id=None):
        work_key = str(provider_book_id or "").strip()
        if not re.fullmatch(r"/works/OL\d+W", work_key):
            return {}

        work = self._get_json(f"{work_key}.json")
        edition_key = _normalize_edition_key(provider_edition_id)
        representative = {}
        if not edition_key:
            candidates = self._request(f"key:{work_key}", 1)
            representative = candidates[0] if candidates else {}
            edition_key = _normalize_edition_key(representative.get("provider_edition_id"))
        edition = self._get_json(f"{edition_key}.json") if edition_key else {}
        description = _text_value(work.get("description"))
        subjects = [
            str(subject).strip()
            for subject in work.get("subjects", [])
            if isinstance(subject, str) and str(subject).strip()
        ][:10]
        isbn = _best_isbn(
            _as_list(edition.get("isbn_13")) + _as_list(edition.get("isbn_10"))
        ) if edition else None
        return {
            "provider_edition_id": edition_key,
            "isbn": isbn or representative.get("isbn"),
            "publisher": _first_text(edition.get("publishers")) or representative.get("publisher"),
            "publish_date": _first_text(edition.get("publish_date"))
            or representative.get("publish_date")
            or _first_text(work.get("first_publish_date")),
            "page_count": _page_count(edition.get("number_of_pages"))
            or representative.get("page_count"),
            "language": _edition_language(edition.get("languages"))
            or representative.get("language"),
            "description": description,
            "physical_format": _first_text(edition.get("physical_format"))
            or representative.get("physical_format"),
            "subtitle": _first_text(edition.get("subtitle")) or _first_text(work.get("subtitle")),
            "subjects": subjects,
        }

    def series(self, provider_book_id, authors=None, limit=24):
        work_key = str(provider_book_id or "").strip()
        if not re.fullmatch(r"/works/OL\d+W", work_key):
            return None

        work = self._get_json(f"{work_key}.json")
        relationships = work.get("series") or []
        if relationships:
            relationship = relationships[0] if isinstance(relationships[0], dict) else {}
            series_value = relationship.get("series") or {}
            series_key = series_value.get("key") if isinstance(series_value, dict) else None
            if series_key and re.fullmatch(r"/series/OL\d+L", series_key):
                details = self._get_json(f"{series_key}.json")
                seeds = self._get_json(f"{series_key}/seeds.json")
                books = _normalize_series_seeds(seeds.get("entries", []), authors, limit)
                current_position = relationship.get("position")
                for index, book in enumerate(books):
                    if book["provider_book_id"] == work_key:
                        book["series_position"] = current_position or index + 1
                return {
                    "name": details.get("name") or "Unbenannte Reihe",
                    "provider_series_id": series_key,
                    "current_position": current_position,
                    "source": "structured",
                    "incomplete": False,
                    "books": books,
                }

        subject_name = _series_subject(work.get("subjects", []))
        if not subject_name:
            return None
        escaped_name = subject_name.replace("\\", "\\\\").replace('"', '\\"')
        subject_books = self._request(f'subject:"series:{escaped_name}"', limit)
        broad_query = f'"{escaped_name}"'
        if authors:
            escaped_author = str(authors[0]).replace("\\", "\\\\").replace('"', '\\"')
            broad_query += f' author:"{escaped_author}"'
        broad_books = self._request(broad_query, min(40, max(limit * 2, 24)))
        candidates = _deduplicate_books([*broad_books, *subject_books])
        edition_details = self._edition_details(candidates)
        positioned = []
        for book in candidates:
            if _is_series_collection_title(book.get("title")):
                continue
            position = _series_position_from_edition(
                edition_details.get(book.get("provider_edition_id"), {}),
                subject_name,
            )
            if position is None:
                continue
            positioned.append({**book, "series_position": position})
        books = _best_positioned_series_books(positioned, work_key, limit)
        if len(books) >= 2:
            current = next(
                (book for book in books if book.get("provider_book_id") == work_key),
                None,
            )
            return {
                "name": subject_name,
                "provider_series_id": None,
                "current_position": current.get("series_position") if current else None,
                "source": "edition",
                "incomplete": True,
                "books": books,
            }

        books = subject_books
        books.sort(key=lambda book: (book.get("first_publish_year") is None, book.get("first_publish_year") or 0))
        for book in books:
            book["series_position"] = None
        return {
            "name": subject_name,
            "provider_series_id": None,
            "current_position": None,
            "source": "subject",
            "incomplete": True,
            "books": books,
        }

    def _edition_details(self, books):
        edition_ids = []
        for book in books:
            edition_id = _normalize_edition_key(book.get("provider_edition_id"))
            if edition_id and edition_id not in edition_ids:
                edition_ids.append(edition_id)
        if not edition_ids:
            return {}
        bibkeys = ",".join(f"OLID:{edition_id.rsplit('/', 1)[-1]}" for edition_id in edition_ids)
        try:
            response = requests.get(
                self.BOOKS_API_URL,
                params={"bibkeys": bibkeys, "jscmd": "details", "format": "json"},
                timeout=(3.05, 10),
                headers=self.REQUEST_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Open Library hat keine gültige JSON-Antwort geliefert.")
        except (requests.RequestException, ValueError) as error:
            raise ProviderUnavailable("Open Library ist derzeit nicht erreichbar.") from error
        details = {}
        for value in payload.values():
            raw = value.get("details") if isinstance(value, dict) else None
            edition_id = _normalize_edition_key(raw.get("key")) if isinstance(raw, dict) else None
            if edition_id:
                details[edition_id] = raw
        return details

    def _get_json(self, path):
        try:
            response = requests.get(
                f"{self.API_URL}{path}",
                timeout=(3.05, 8),
                headers=self.REQUEST_HEADERS,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            raise ProviderUnavailable("Open Library ist derzeit nicht erreichbar.") from error


def _prefix_query(query):
    tokens = [token for token in str(query).split() if token]
    escaped = [_escape_solr(token) for token in tokens]
    if not escaped:
        return ""
    prefix = " AND ".join([*escaped[:-1], f"{escaped[-1]}*"])
    return f"title:({prefix}) OR author:({prefix}) OR isbn:({prefix})"


def _retryable_search_error(error):
    if isinstance(error, ValueError):
        return True
    if isinstance(error, requests.HTTPError):
        response = error.response
        status = response.status_code if response is not None else None
        return status == 429 or bool(status and status >= 500)
    return isinstance(error, (requests.ConnectionError, requests.Timeout))


def _tolerant_prefix_query(query):
    tokens = [token for token in str(query).split() if token]
    if not tokens:
        return ""
    last = tokens[-1]
    if len(last) >= 7:
        last = last[:-2]
    elif len(last) >= 3:
        last = last[:-1]
    escaped = [_escape_solr(token) for token in [*tokens[:-1], last]]
    terms = " AND ".join([*escaped[:-1], f"{escaped[-1]}*"])
    return f"title:({terms}) OR author:({terms}) OR isbn:({terms})"


def _closest_results(query, books, limit):
    if not books:
        return []
    normalized_query = _simple_normalize(query)

    def score(index):
        book = books[index]
        return (_book_match_score(normalized_query, book), -index)

    lead_index = max(range(len(books)), key=score)
    # Nur der beste Titel wird nach vorn gehoben. Die übrige Open-Library-
    # Reihenfolge bleibt erhalten, weil sie oft passende Reihen-Nachbarn enthält.
    ordered = [books[lead_index], *(book for index, book in enumerate(books) if index != lead_index)]
    return ordered[:limit]


def _book_match_score(query, book):
    normalized_query = _simple_normalize(query)
    if not normalized_query:
        return 0.0
    authors = book.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    candidates = [book.get("title"), " ".join(authors), book.get("isbn")]
    return max(
        (_text_match_score(normalized_query, _simple_normalize(value)) for value in candidates),
        default=0.0,
    )


def _text_match_score(query, candidate):
    if not candidate:
        return 0.0
    if candidate == query:
        return 4.0
    similarity = SequenceMatcher(None, query, candidate).ratio()
    if candidate.startswith(query):
        return 3.0 + similarity
    query_words = query.split()
    candidate_words = candidate.split()
    candidate_index = 0
    ordered_prefix_match = bool(query_words)
    for query_word in query_words:
        while (
            candidate_index < len(candidate_words)
            and not candidate_words[candidate_index].startswith(query_word)
        ):
            candidate_index += 1
        if candidate_index == len(candidate_words):
            ordered_prefix_match = False
            break
        candidate_index += 1
    if ordered_prefix_match:
        return 2.5 + similarity
    return similarity


def _deduplicate_books(books):
    result = []
    seen = set()
    for book in books:
        identity = (
            book.get("provider_book_id")
            or book.get("isbn")
            or (_simple_normalize(book.get("title")), tuple(book.get("authors") or []))
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(book)
    return result


def _simple_normalize(value):
    return " ".join(re.findall(r"\w+", str(value or "").casefold(), flags=re.UNICODE))


def _rank_books(books):
    """Prefer covered results while preserving Open Library relevance within each group."""
    return sorted(books, key=lambda book: not bool(book.get("cover_url")))


def _matching_edition(item):
    editions = item.get("editions") or {}
    documents = editions.get("docs", []) if isinstance(editions, dict) else []
    return documents[0] if documents and isinstance(documents[0], dict) else {}


def _display_authors(authors, alternatives):
    names = [str(author).strip() for author in (authors or []) if str(author).strip()][:4]
    if not names or re.search(r"[A-Za-z]", names[0]):
        return names
    other_author_keys = {
        re.sub(r"[^a-z0-9]+", "", name.casefold()) for name in names[1:]
    }
    latin_alternatives = [
        str(name).strip()
        for name in alternatives or []
        if re.search(r"[A-Za-z]", str(name))
        and re.sub(r"[^a-z0-9]+", "", str(name).casefold()) not in other_author_keys
    ]
    if latin_alternatives:
        natural_case = [
            name
            for name in latin_alternatives
            if 1 < len(name.split()) < 5 and name != name.upper()
        ]
        names[0] = (natural_case or latin_alternatives)[-1]
    return names


def _is_latin_translation(original_title, edition_title):
    return (
        bool(original_title)
        and bool(edition_title)
        and not re.search(r"[A-Za-z]", original_title)
        and bool(re.search(r"[A-Za-z]", edition_title))
    )


def _normalize_work_key(value):
    key = str(value or "").strip()
    if re.fullmatch(r"OL\d+W", key):
        return f"/works/{key}"
    return key or None


def _normalize_edition_key(value):
    key = str(value or "").strip()
    if re.fullmatch(r"OL\d+M", key):
        return f"/books/{key}"
    return key if re.fullmatch(r"/books/OL\d+M", key) else None


def _cover_url(record):
    cover_id = record.get("cover_i") if isinstance(record, dict) else None
    if isinstance(cover_id, list):
        cover_id = cover_id[0] if cover_id else None
    if cover_id:
        return f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
    return None


def _edition_language(languages):
    if not languages:
        return None
    value = languages[0] if isinstance(languages, list) else languages
    if isinstance(value, dict):
        value = value.get("key")
    return str(value or "").rsplit("/", 1)[-1] or None


def _escape_solr(value):
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/])', r"\\\1", value)


def _best_isbn(isbns):
    if isinstance(isbns, str):
        isbns = [isbns]
    normalized = ["".join(char for char in value.upper() if char.isdigit() or char == "X") for value in isbns]
    return next((value for value in normalized if len(value) == 13), None) or next(
        (value for value in normalized if len(value) == 10), None
    )


def _page_count(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, bool):
        return None
    try:
        pages = int(value)
    except (TypeError, ValueError):
        return None
    return pages if pages > 0 else None


def _first_text(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "").strip() or None


def _as_list(value):
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def _text_value(value):
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "").strip() or None


def _series_subject(subjects):
    for subject in subjects or []:
        if isinstance(subject, str) and subject.casefold().startswith("series:"):
            name = subject.split(":", 1)[1].strip()
            if name:
                return name
    return None


_POSITION_WORDS = {
    "one": 1, "first": 1, "eins": 1, "erste": 1, "erster": 1,
    "two": 2, "second": 2, "zwei": 2, "zweite": 2, "zweiter": 2,
    "three": 3, "third": 3, "drei": 3, "dritte": 3, "dritter": 3,
    "four": 4, "fourth": 4, "vier": 4, "vierte": 4, "vierter": 4,
    "five": 5, "fifth": 5, "fünf": 5, "fuenf": 5, "fünfte": 5,
    "six": 6, "sixth": 6, "sechs": 6, "sechste": 6,
    "seven": 7, "seventh": 7, "sieben": 7, "siebte": 7,
    "eight": 8, "eighth": 8, "acht": 8, "achte": 8,
    "nine": 9, "ninth": 9, "neun": 9, "neunte": 9,
    "ten": 10, "tenth": 10, "zehn": 10, "zehnte": 10,
}
_POSITION_MARKERS = {"book", "volume", "vol", "band", "teil", "tome"}


def _position_token(value):
    token = str(value or "").casefold().strip(".#,;:()[]")
    numeric = re.fullmatch(r"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?", token)
    if numeric:
        number = float(numeric.group(1))
        return int(number) if number.is_integer() else number
    return _POSITION_WORDS.get(token)


def _series_position_from_edition(details, series_name):
    if not isinstance(details, dict):
        return None
    values = []
    for field in ("series", "subtitle", "full_title", "title", "notes"):
        value = details.get(field)
        if isinstance(value, dict):
            value = value.get("value")
        values.extend(value if isinstance(value, list) else [value])
    series_tokens = _simple_normalize(series_name).split()
    if not series_tokens:
        return None
    for value in values:
        tokens = _simple_normalize(value).split()
        if not tokens:
            continue
        for start in range(0, len(tokens) - len(series_tokens) + 1):
            if tokens[start:start + len(series_tokens)] != series_tokens:
                continue
            before = tokens[max(0, start - 5):start]
            after = tokens[start + len(series_tokens):start + len(series_tokens) + 5]
            for index, token in enumerate(after[:4]):
                position = _position_token(token)
                if position is not None and (
                    index == 0 or any(marker in after[:index] for marker in _POSITION_MARKERS)
                ):
                    return position
            for index, token in enumerate(before):
                position = _position_token(token)
                if position is not None and any(
                    marker in before[:index] for marker in _POSITION_MARKERS
                ):
                    return position
    return None


def _is_series_collection_title(title):
    normalized = _simple_normalize(title)
    return any(
        phrase in normalized
        for phrase in ("collection set", "books collection", "boxed set", "box set", "bundle")
    )


def _best_positioned_series_books(books, current_work_key, limit):
    by_position = {}
    for book in books:
        position = book.get("series_position")
        if position is None:
            continue
        title = _simple_normalize(book.get("title"))
        score = (
            100 if book.get("provider_book_id") == current_work_key else 0,
            -20 if re.search(r"\b(?:part|volume|vol)\b", title) else 0,
            4 if book.get("cover_url") else 0,
            2 if book.get("page_count") else 0,
            1 if book.get("isbn") else 0,
        )
        previous = by_position.get(str(position))
        if previous is None or score > previous[0]:
            by_position[str(position)] = (score, book)
    selected = [entry[1] for entry in by_position.values()]
    selected.sort(key=lambda book: (float(book["series_position"]), _simple_normalize(book["title"])))
    return selected[:limit]


def _normalize_series_seeds(entries, authors, limit):
    books = []
    for index, entry in enumerate(entries or []):
        if len(books) >= limit or entry.get("type") != "work":
            continue
        title = str(entry.get("title") or "").strip()
        work_key = str(entry.get("url") or "").strip()
        if not title or not re.fullmatch(r"/works/OL\d+W", work_key):
            continue
        picture = entry.get("picture") or {}
        cover_url = picture.get("url") if isinstance(picture, dict) else None
        if cover_url:
            cover_url = f"https:{cover_url}" if cover_url.startswith("//") else cover_url
            cover_url = cover_url.replace("-S.jpg", "-M.jpg")
        books.append(
            {
                "provider": "open_library",
                "provider_book_id": work_key,
                "title": title,
                "authors": list(authors or []),
                "isbn": None,
                "cover_url": cover_url,
                "first_publish_year": None,
                "page_count": _page_count(entry.get("number_of_pages")),
                "series_position": index + 1,
            }
        )
    return books

