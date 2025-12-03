def analyze_text(text: str) -> dict:
    """
    Safe introspection tool — analiza teksta bez AICommandService.
    """

    return {
        "received_text": text,
        "length": len(text),
        "is_question": text.strip().endswith("?"),
        "contains_numbers": any(ch.isdigit() for ch in text),
        "word_count": len(text.split()),
        "uppercase_ratio": sum(ch.isupper() for ch in text) / max(1, len(text)),
        "diagnostic": "Safe analysis completed."
    }
