from flask import current_app

from .open_library import OpenLibraryProvider


def create_provider(configured="open_library"):
    if configured == "open_library":
        return OpenLibraryProvider()
    raise RuntimeError(f"Unbekannter Buchanbieter: {configured}")


def get_provider():
    return create_provider(current_app.config.get("BOOK_PROVIDER", "open_library"))

