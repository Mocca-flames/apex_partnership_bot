import re


SA_PREFIX = "27"
SA_HUMAN_PREFIX = "0"
SA_HUMAN_LENGTH = 10
SA_INTERNATIONAL_LENGTH = 11


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return digits
    if digits.startswith(SA_HUMAN_PREFIX) and len(digits) == SA_HUMAN_LENGTH:
        return SA_PREFIX + digits[1:]
    if digits.startswith(SA_PREFIX) and len(digits) == SA_INTERNATIONAL_LENGTH:
        return digits
    return digits


def is_sa_number(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return (digits.startswith(SA_HUMAN_PREFIX) and len(digits) == SA_HUMAN_LENGTH) or (
        digits.startswith(SA_PREFIX) and len(digits) == SA_INTERNATIONAL_LENGTH
    )