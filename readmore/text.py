import unicodedata


def normalize_text(value):
    """Normalize for matching while retaining letters and numbers from every script."""
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    words = []
    current = []
    for character in value:
        if unicodedata.combining(character):
            continue
        if character.isalnum():
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return " ".join(words)


def identity_key(title, authors):
    return f"{normalize_text(title)}|{normalize_text(authors)}"
