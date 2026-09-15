"""
Self-contained synthetic PHI value generator.

Deliberately does NOT depend on the `faker` library so this runs anywhere
(including offline / inside a locked-down container) with zero extra
dependencies beyond reportlab. Every value returned here is fabricated -
no real patient, physician, or hospital data is used anywhere.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta

FIRST_NAMES = [
    "Aarav", "Priya", "Wei", "Fatima", "Liam", "Sofia", "Kenji", "Amara",
    "Noah", "Isabella", "Diego", "Mei", "Ivan", "Chidi", "Elena", "Omar",
    "Grace", "Hiroshi", "Layla", "Marcus", "Nadia", "Oskar", "Ravi",
    "Sana", "Tomas", "Yuki", "Zara", "Bilal", "Camila", "Dmitri",
]
LAST_NAMES = [
    "Sharma", "Nguyen", "Garcia", "Muller", "Kowalski", "Okafor", "Kim",
    "Rossi", "Andersson", "Ivanov", "Silva", "Tanaka", "Haddad", "Novak",
    "Petrov", "Fernandez", "Yamamoto", "Osei", "Dubois", "Larsen",
    "Costa", "Wallace", "Mensah", "Popescu", "Nakamura", "Berg",
]
PHYSICIAN_LAST_NAMES = LAST_NAMES + ["Whitfield", "Okonjo", "Castellano", "Bergstrom"]
HOSPITAL_NAMES = [
    "Origin Hospital", "Meridian General Hospital", "St. Aldric Medical Center",
    "Northgate Regional Hospital", "Lakeshore Health Institute",
    "Union Valley Medical Center", "Sunridge Community Hospital",
    "Ashford Diagnostic Center", "Harborview Clinical Institute",
]
STREET_NAMES = ["Maple Ave", "5th Street", "Kestrel Road", "Willow Lane", "Harbor Blvd"]
CITY_NAMES = ["Millbrook", "Fairview", "Riverton", "Ashford", "Brookhaven", "Cedar Falls"]

MODALITY_TEMPLATES = ["ultrasound", "radiology", "lab"]


def _rand_digits(n: int) -> str:
    return "".join(random.choices(string.digits, k=n))


def random_patient_id() -> str:
    return _rand_digits(5)


def random_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def random_physician_name() -> str:
    return f"Dr. {random.choice(FIRST_NAMES)} {random.choice(PHYSICIAN_LAST_NAMES)}"


def random_hospital() -> str:
    return random.choice(HOSPITAL_NAMES)


def random_address() -> str:
    return f"{random.randint(10, 9999)} {random.choice(STREET_NAMES)}, {random.choice(CITY_NAMES)}"


def random_phone() -> str:
    return f"({_rand_digits(3)}) {_rand_digits(3)}-{_rand_digits(4)}"


def random_dob(min_age: int = 1, max_age: int = 90) -> date:
    age_years = random.randint(min_age, max_age)
    today = date.today()
    try:
        return today.replace(year=today.year - age_years,
                              month=random.randint(1, 12),
                              day=random.randint(1, 28))
    except ValueError:
        return today - timedelta(days=age_years * 365)


def random_exam_date(days_back_max: int = 900) -> date:
    return date.today() - timedelta(days=random.randint(0, days_back_max))


def random_gender() -> str:
    return random.choice(["Male", "Female"])


def random_bool_finding(abnormal_rate: float = 0.15) -> bool:
    return random.random() < abnormal_rate


@dataclass
class PatientRecord:
    """One synthetic patient's demographic + document metadata.

    This is the object that ultimately gets written, verbatim, into the
    answer-key CSV - it IS the ground truth your de-id pipeline should be
    scrubbing out.
    """
    patient_id: str
    patient_name: str
    gender: str
    dob: date
    age_years: int
    physician_name: str
    hospital_name: str
    address: str
    phone: str
    template: str
    extra: dict = field(default_factory=dict)


def generate_patient_record(template: str) -> PatientRecord:
    if template == "ultrasound":
        # obstetric scan: female patient, plausible childbearing age
        dob = random_dob(min_age=18, max_age=42)
        gender = "Female"
    else:
        dob = random_dob()
        gender = random_gender()
    age = date.today().year - dob.year
    return PatientRecord(
        patient_id=random_patient_id(),
        patient_name=random_name(),
        gender=gender,
        dob=dob,
        age_years=age,
        physician_name=random_physician_name(),
        hospital_name=random_hospital(),
        address=random_address(),
        phone=random_phone(),
        template=template,
    )
