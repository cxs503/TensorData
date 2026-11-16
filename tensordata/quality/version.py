"""Product identity for the physics dataset validator (PROD-PV).

The validator is a product line, not a single module: the quality engine
(``rules/``, ``engine.py``), the physics CSV adapter (``physics_csv.py``), the
unit registry (``units.py``) and the column identification layer
(``fields.py``) ship together and are versioned together here. The report
payload written by :func:`tensordata.quality.physics_csv.validate_physics_csv`
stamps this identity, so every verdict is bound to the product version that
produced it.

``PRODUCT_VERSION`` follows semantic versioning for the *deliverable*:
- MAJOR: a verdict that passed under an older version may fail (or vice versa)
  without a profile/dataset change;
- MINOR: new checks or newly identified fields, existing passing datasets stay
  passing;
- PATCH: fixes that do not change any verdict on conforming datasets.

Release notes live in ``docs/CHANGELOG.md``; ``tests/test_pv_product.py``
asserts the two cannot drift apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

PRODUCT_ID = "physics-dataset-validator"
PRODUCT_VERSION = "1.0.0"
#: Schema version of the emitted validation report payload (unchanged by the
#: 1.0.0 product release: the report shape is already consumed downstream).
REPORT_SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class ProductIdentity:
    product_id: str = PRODUCT_ID
    product_version: str = PRODUCT_VERSION
    report_schema_version: str = REPORT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def describe(self) -> str:
        return f"{self.product_id} {self.product_version} (report schema {self.report_schema_version})"


IDENTITY = ProductIdentity()

__all__ = [
    "IDENTITY",
    "PRODUCT_ID",
    "PRODUCT_VERSION",
    "ProductIdentity",
    "REPORT_SCHEMA_VERSION",
]