import re

from app.models import Driver

LICENSE_PATTERN = re.compile(r"^[A-Z]\d{7}$")


def is_verifiable(driver: Driver) -> bool:
    return bool(LICENSE_PATTERN.match(driver.license_no))
