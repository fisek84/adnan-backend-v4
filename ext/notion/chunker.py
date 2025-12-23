def chunk_text(text: str, max_len: int = 1800):
    """
    Dijeli veliki tekst na manje blokove (chunkove)
    koji su dovoljno mali da ih Notion prihvati.
    """
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]
