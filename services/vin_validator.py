"""VIN check digit validation per ISO 3779."""


def vin_check_digit(vin: str) -> bool:
    """Validate VIN check digit (position 9) per ISO 3779. Returns True if valid or non-applicable."""
    if not vin or len(vin) != 17:
        return False
    transliteration = {
        'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
        'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
        'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
    }
    weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
    total = 0
    for i, ch in enumerate(vin.upper()):
        if ch.isdigit():
            val = int(ch)
        else:
            val = transliteration.get(ch)
            if val is None:
                return False
        total += val * weights[i]
    remainder = total % 11
    check = 'X' if remainder == 10 else str(remainder)
    return vin[8] == check
