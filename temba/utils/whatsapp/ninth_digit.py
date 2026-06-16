import re

# The generated variant (without the 9th digit) must keep at least this many digits.
# 4 keeps "99676" -> "9676" working while blocking "9676" -> "676", which matched
# thousands of unrelated contacts in production benchmarks.
MIN_VARIANT_LEN = 4


def get_number_search_variations(number: str) -> list:
    """
    Returns the number plus its variant without the Brazilian extra 9th digit.

    Only the no-9 variant is generated because the trigram index already covers the
    opposite direction (typed without 9 -> contact stored with 9). The variant is
    only added when it keeps at least MIN_VARIANT_LEN digits, to avoid overly broad
    short fragments.
    """
    digits = re.sub(r"\D", "", number)
    variations = [digits]

    stripped = None
    if digits.startswith("55") and len(digits) >= 5 and digits[4] == "9":
        stripped = digits[:4] + digits[5:]
    elif len(digits) == 11 and digits[2] == "9":
        stripped = digits[:2] + digits[3:]
    elif digits.startswith("9"):
        stripped = digits[1:]

    if stripped and len(stripped) >= MIN_VARIANT_LEN:
        variations.append(stripped)

    seen = set()
    return [v for v in variations if len(v) >= 3 and not (v in seen or seen.add(v))]
