from abc import ABC, abstractmethod


class BookProvider(ABC):
    """Small boundary that keeps third-party catalogue formats out of the app."""

    @abstractmethod
    def search(self, query, limit=12):
        """Return normalized book dictionaries."""
        raise NotImplementedError

    def suggest(self, query, limit=6):
        """Return short type-ahead results; providers may optimize prefix matching."""
        return self.search(query, limit=limit)

    def series(self, provider_book_id, authors=None, limit=24):
        """Return normalized series details when the catalogue provides them."""
        return None

    def metadata(self, provider_book_id, provider_edition_id=None):
        """Return optional edition and work metadata for a detail view."""
        return {}

