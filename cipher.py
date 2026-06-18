# Словарь эмодзи -> буквы (без пробелов!)
EMOJI_TO_LETTER = {
    "🟢": "А", "🔵": "Б", "🔴": "В", "🟠": "Г", "🟡": "Д",
    "⚫": "Е", "⚪": "Ё", "🟣": "Ж", "🟤": "З", "🔶": "И",
    "🔷": "Й", "⬛": "К", "⬜": "Л", "🟥": "М", "🟧": "Н",
    "🟨": "О", "🟩": "П", "🟦": "Р", "🟪": "С", "🔘": "Т",
    "🔺": "У", "🔻": "Ф", "💚": "Х", "💙": "Ц", "💜": "Ч",
    "🧡": "Ш", "🖤": "Щ", "🤍": "Ъ", "🤎": "Ы", "💛": "Ь",
    "🩵": "Э", "🩷": "Ю", "🩶": "Я"
}

# Обратный словарь: буква -> эмодзи
LETTER_TO_EMOJI = {v: k for k, v in EMOJI_TO_LETTER.items()}


def encode(text: str) -> str:
    """Кодирует текст в эмодзи."""
    result = []
    for ch in text.upper():
        if ch in LETTER_TO_EMOJI:
            result.append(LETTER_TO_EMOJI[ch])
        else:
            result.append(ch)  # Пробелы и знаки препинания остаются
    return "".join(result)


def decode(text: str) -> str:
    """Расшифровывает эмодзи обратно в текст."""
    result = []
    for ch in text:
        if ch in EMOJI_TO_LETTER:
            result.append(EMOJI_TO_LETTER[ch])
        else:
            result.append(ch)  # Пробелы и знаки препинания остаются
    return "".join(result)