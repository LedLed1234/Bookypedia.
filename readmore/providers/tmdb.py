import requests

from .base import ProviderUnavailable


class TMDBProvider:
    """Small TMDB boundary for movie and TV search results."""

    SEARCH_URL = "https://api.themoviedb.org/3/search/multi"
    MOVIE_DETAILS_URL = "https://api.themoviedb.org/3/movie/{movie_id}"
    COLLECTION_URL = "https://api.themoviedb.org/3/collection/{collection_id}"
    TV_DETAILS_URL = "https://api.themoviedb.org/3/tv/{series_id}"
    TV_SEASON_URL = "https://api.themoviedb.org/3/tv/{series_id}/season/{season_number}"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
    REQUEST_TIMEOUT = (3.05, 10)

    def __init__(self, read_access_token):
        self.read_access_token = str(read_access_token or "").strip()
        self.cache_identity = "tmdb:de-DE:DE"

    def search(self, query, limit=12):
        payload = self._request_json(
            self.SEARCH_URL,
            params={
                "query": query,
                "language": "de-DE",
                "region": "DE",
                "include_adult": "false",
                "page": 1,
            },
        )

        requested_limit = min(20, max(1, int(limit)))
        results = []
        for item in payload.get("results", []):
            normalized = self._normalize_result(item)
            if normalized:
                results.append(normalized)
            if len(results) >= requested_limit:
                break
        return results

    def movie_collection(self, movie_id):
        movie_id = self._positive_int(movie_id)
        if movie_id is None:
            return None
        movie = self._request_json(
            self.MOVIE_DETAILS_URL.format(movie_id=movie_id),
            params={"language": "de-DE"},
        )
        reference = movie.get("belongs_to_collection")
        if not isinstance(reference, dict):
            return None
        collection_id = self._positive_int(reference.get("id"))
        if collection_id is None:
            return None
        payload = self._request_json(
            self.COLLECTION_URL.format(collection_id=collection_id),
            params={"language": "de-DE"},
        )
        name = str(payload.get("name") or reference.get("name") or "").strip()
        if not name:
            return None
        parts = []
        for item in payload.get("parts", []):
            normalized = self._normalize_collection_part(item)
            if normalized:
                parts.append(normalized)
        parts.sort(key=lambda item: (item.get("release_date") or "9999-99-99", item["title"]))
        for position, part in enumerate(parts, start=1):
            part["collection_position"] = position
        poster_path = self._image_path(payload.get("poster_path"))
        backdrop_path = self._image_path(payload.get("backdrop_path"))
        return {
            "provider": "tmdb",
            "tmdb_id": collection_id,
            "name": name,
            "overview": str(payload.get("overview") or "").strip() or None,
            "cover_url": f"{self.IMAGE_BASE_URL}/w500{poster_path}" if poster_path else None,
            "backdrop_url": f"{self.IMAGE_BASE_URL}/w780{backdrop_path}" if backdrop_path else None,
            "parts": parts,
        }

    def tv_seasons(self, series_id):
        series_id = self._positive_int(series_id)
        if series_id is None:
            return None
        payload = self._request_json(
            self.TV_DETAILS_URL.format(series_id=series_id),
            params={"language": "de-DE"},
        )
        name = str(payload.get("name") or payload.get("original_name") or "").strip()
        seasons = []
        for item in payload.get("seasons", []):
            normalized = self._normalize_season(item)
            if normalized:
                seasons.append(normalized)
        seasons.sort(key=lambda item: item["season_number"])
        return {
            "provider": "tmdb",
            "tmdb_id": series_id,
            "name": name or "Serie",
            "number_of_seasons": len(seasons),
            "seasons": seasons,
        }

    def tv_season(self, series_id, season_number):
        series_id = self._positive_int(series_id)
        season_number = self._positive_int(season_number)
        if series_id is None or season_number is None:
            return None
        payload = self._request_json(
            self.TV_SEASON_URL.format(
                series_id=series_id,
                season_number=season_number,
            ),
            params={"language": "de-DE"},
        )
        episodes = []
        for item in payload.get("episodes", []):
            normalized = self._normalize_episode(item)
            if normalized:
                episodes.append(normalized)
        episodes.sort(key=lambda item: item["episode_number"])
        poster_path = self._image_path(payload.get("poster_path"))
        return {
            "provider": "tmdb",
            "tmdb_id": series_id,
            "season_number": season_number,
            "name": str(payload.get("name") or f"Staffel {season_number}").strip(),
            "overview": str(payload.get("overview") or "").strip() or None,
            "air_date": str(payload.get("air_date") or "").strip() or None,
            "cover_url": f"{self.IMAGE_BASE_URL}/w342{poster_path}" if poster_path else None,
            "episodes": episodes,
        }

    def _request_json(self, url, *, params):
        if not self.read_access_token:
            raise ProviderUnavailable(
                "TMDB ist noch nicht konfiguriert. Hinterlege den Read Access Token in der .env-Datei."
            )
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {self.read_access_token}",
                    "Accept": "application/json",
                    "User-Agent": "Moviepedia/1.0 (personal media manager)",
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            if response.status_code in (401, 403):
                raise ProviderUnavailable(
                    "Der TMDB-Zugang wurde abgelehnt. Prüfe den Read Access Token in der .env-Datei."
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("TMDB hat keine gültige JSON-Antwort geliefert.")
            return payload
        except ProviderUnavailable:
            raise
        except (requests.RequestException, ValueError) as error:
            raise ProviderUnavailable("TMDB ist derzeit nicht erreichbar.") from error

    @classmethod
    def _normalize_result(cls, item):
        if not isinstance(item, dict):
            return None
        media_type = str(item.get("media_type") or "").strip()
        if media_type not in {"movie", "tv"}:
            return None
        tmdb_id = item.get("id")
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            return None

        title_key = "title" if media_type == "movie" else "name"
        original_title_key = "original_title" if media_type == "movie" else "original_name"
        release_date_key = "release_date" if media_type == "movie" else "first_air_date"
        title = str(item.get(title_key) or "").strip()
        if not title:
            return None
        original_title = str(item.get(original_title_key) or "").strip()
        release_date = str(item.get(release_date_key) or "").strip() or None
        poster_path = cls._image_path(item.get("poster_path"))
        backdrop_path = cls._image_path(item.get("backdrop_path"))

        return {
            "provider": "tmdb",
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "title": title,
            "original_title": original_title if original_title and original_title != title else None,
            "overview": str(item.get("overview") or "").strip() or None,
            "release_date": release_date,
            "release_year": cls._release_year(release_date),
            "original_language": str(item.get("original_language") or "").strip() or None,
            "cover_url": f"{cls.IMAGE_BASE_URL}/w500{poster_path}" if poster_path else None,
            "backdrop_url": f"{cls.IMAGE_BASE_URL}/w780{backdrop_path}" if backdrop_path else None,
            "vote_average": cls._number(item.get("vote_average")),
            "vote_count": cls._positive_int(item.get("vote_count")) or 0,
            "popularity": cls._number(item.get("popularity")),
        }

    @classmethod
    def _normalize_collection_part(cls, item):
        if not isinstance(item, dict):
            return None
        tmdb_id = item.get("id")
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            return None
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            return None
        original_title = str(
            item.get("original_title") or item.get("original_name") or ""
        ).strip()
        release_date = str(item.get("release_date") or "").strip() or None
        poster_path = cls._image_path(item.get("poster_path"))
        backdrop_path = cls._image_path(item.get("backdrop_path"))
        return {
            "provider": "tmdb",
            "tmdb_id": tmdb_id,
            "media_type": "movie",
            "title": title,
            "original_title": original_title if original_title and original_title != title else None,
            "overview": str(item.get("overview") or "").strip() or None,
            "release_date": release_date,
            "release_year": cls._release_year(release_date),
            "original_language": str(item.get("original_language") or "").strip() or None,
            "cover_url": f"{cls.IMAGE_BASE_URL}/w342{poster_path}" if poster_path else None,
            "backdrop_url": f"{cls.IMAGE_BASE_URL}/w780{backdrop_path}" if backdrop_path else None,
            "vote_average": cls._number(item.get("vote_average")),
            "vote_count": cls._positive_int(item.get("vote_count")) or 0,
        }

    @classmethod
    def _normalize_season(cls, item):
        if not isinstance(item, dict):
            return None
        season_number = cls._positive_int(item.get("season_number"))
        if season_number is None:
            return None
        name = str(item.get("name") or f"Staffel {season_number}").strip()
        poster_path = cls._image_path(item.get("poster_path"))
        return {
            "tmdb_id": cls._positive_int(item.get("id")),
            "season_number": season_number,
            "name": name,
            "overview": str(item.get("overview") or "").strip() or None,
            "air_date": str(item.get("air_date") or "").strip() or None,
            "episode_count": cls._positive_int(item.get("episode_count")) or 0,
            "cover_url": f"{cls.IMAGE_BASE_URL}/w342{poster_path}" if poster_path else None,
        }

    @classmethod
    def _normalize_episode(cls, item):
        if not isinstance(item, dict):
            return None
        episode_number = cls._positive_int(item.get("episode_number"))
        if episode_number is None:
            return None
        name = str(item.get("name") or f"Episode {episode_number}").strip()
        still_path = cls._image_path(item.get("still_path"))
        return {
            "tmdb_id": cls._positive_int(item.get("id")),
            "episode_number": episode_number,
            "name": name,
            "overview": str(item.get("overview") or "").strip() or None,
            "air_date": str(item.get("air_date") or "").strip() or None,
            "runtime": cls._positive_int(item.get("runtime")),
            "still_url": f"{cls.IMAGE_BASE_URL}/w300{still_path}" if still_path else None,
            "vote_average": cls._number(item.get("vote_average")),
            "vote_count": cls._positive_int(item.get("vote_count")) or 0,
        }

    @staticmethod
    def _image_path(value):
        path = str(value or "").strip()
        return path if path.startswith("/") and ".." not in path else None

    @staticmethod
    def _release_year(value):
        text = str(value or "")
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1870 <= year <= 3000:
                return year
        return None

    @staticmethod
    def _number(value):
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _positive_int(value):
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None
