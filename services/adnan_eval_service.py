def evaluate_text(input_text: str):
    """
    Sigurna evaluacija teksta bez pokretanja AI modela.
    Ovo je 'pasivna' analiza i služi samo za testiranje pipeline-a.
    """
    return {
        "received_text": input_text,
        "length": len(input_text),
        "is_question": input_text.strip().endswith("?"),
        "contains_numbers": any(char.isdigit() for char in input_text),
        "diagnostic": "Safe evaluation completed."
    }
