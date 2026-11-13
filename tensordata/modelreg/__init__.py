"""Model asset registry: versioned model manifests, hashes and load-and-use.

Public surface::

    from tensordata.modelreg import ModelRegistry, load_model
    reg = ModelRegistry()                       # TENSORDATA_MODEL_REGISTRY_ROOT
    reg.list_models()                           # catalogue rows
    reg.verify("dtmb5415-surrogate-mlp")        # weights + data fingerprint recheck
    model = load_model(reg, "dtmb5415-surrogate-mlp")
    y = model.predict(X)                        # (n, 27) -> (n, 9)
"""

from .loaders import LoaderError, Predictor, load_model
from .registry import ModelRegistry, RegistryError, open_registry, summary_row
from .schema import (
    ManifestError,
    SCHEMA_VERSION,
    assert_valid,
    canonical_checksum,
    canonical_json,
    check_artifact_files,
    check_training_binding,
    fingerprint_arrays,
    finalize,
    sha256_file,
    validate_manifest,
)

__all__ = [
    "LoaderError",
    "ManifestError",
    "ModelRegistry",
    "Predictor",
    "RegistryError",
    "SCHEMA_VERSION",
    "assert_valid",
    "canonical_checksum",
    "canonical_json",
    "check_artifact_files",
    "check_training_binding",
    "finalize",
    "fingerprint_arrays",
    "load_model",
    "open_registry",
    "sha256_file",
    "summary_row",
    "validate_manifest",
]