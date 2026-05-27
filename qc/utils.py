import re

REGISTRATION_NO_MIN_LENGTH = 8


def is_valid_reg_no(reg_no: str) -> str | None:
    registration_number = _clean_plate_number(reg_no)

    if not registration_number:
        return None

    if len(registration_number) >= REGISTRATION_NO_MIN_LENGTH and re.match(
        r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$",
        registration_number,
    ):
        return registration_number.upper()

    return None


def _clean_plate_number(rc_number: str) -> str | None:
    if not rc_number:
        return None
    rc_number_clean = re.sub(r"[^\w]+", "", rc_number, flags=re.ASCII)
    return rc_number_clean.upper()


def generate_vehicle_name(
    make: str,
    model: str,
    variant: str | None = None,
) -> str:
    mmv = f"{make} {model} {variant or ''}"

    mmv_substrings = list(mmv.split(" "))
    uniq_mmv_substrings = []
    for s in mmv_substrings:
        if s not in uniq_mmv_substrings:
            uniq_mmv_substrings.append(s)
    return " ".join(uniq_mmv_substrings)
