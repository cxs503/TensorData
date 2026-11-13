"""Load-and-use layer: turn a registered manifest into a callable predictor.

Two loader kinds are defined, and both are *declared by the manifest* rather
than inferred:

``numpy-affine``
    ``weights.npz`` holding ``W`` (n_out, n_in) and ``b`` (n_out,).  Used for
    linear/ridge baselines and for tests; needs only numpy.

``torch-mlp``
    ``weights/model.pt`` holding a ``state_dict`` for a plain MLP whose layer
    widths are declared in ``io_contract.loader.layers``.  Torch is imported
    lazily, so registration, inventory and verification work on installations
    without it.

Pre/post-processing is read from ``io_contract.preprocessing`` — never guessed —
which is what makes a model asset reproducible instead of a bare checkpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .registry import ModelRegistry

_ACTIVATIONS = {"relu": "relu", "gelu": "gelu", "tanh": "tanh", "silu": "silu", "none": None}


class LoaderError(RuntimeError):
    pass


class Predictor:
    """A loaded model: manifest + forward pass + applicability-domain checks."""

    def __init__(self, manifest: Mapping[str, Any], model_dir: Path, forward) -> None:
        self.manifest = dict(manifest)
        self.model_dir = Path(model_dir)
        self._forward = forward
        self.model_id = manifest["model_id"]
        self.version = manifest["version"]
        self.input_spec = manifest["io_contract"]["inputs"][0]
        self.output_spec = manifest["io_contract"]["outputs"][0]
        self.input_names = list(self.input_spec.get("columns") or
                                [f"in_{i}" for i in range(_width(self.input_spec))])
        self.output_names = list(self.output_spec.get("columns") or
                                 [t["name"] for t in manifest["task"].get("targets", [])] or
                                 [f"out_{i}" for i in range(_width(self.output_spec))])

    # -- forward ----------------------------------------------------------- #
    def predict(self, inputs: Any) -> Any:
        import numpy as np

        X = np.asarray(inputs, dtype=float)
        if X.ndim == 1:
            X = X[None, :]
        expected = _width(self.input_spec)
        if X.ndim != 2 or X.shape[1] != expected:
            raise LoaderError(f"{self.model_id}@{self.version} expects shape (n, {expected}), "
                              f"got {X.shape}")
        return self._forward(X)

    def predict_report(self, inputs: Any) -> dict:
        import numpy as np

        Y = self.predict(inputs)
        violations = self.domain_violations(inputs)
        policy = self.manifest["applicability_domain"].get("out_of_domain_policy", "flag")
        if violations["n_out_of_domain"] and policy == "reject":
            raise LoaderError(f"{self.model_id}: {violations['n_out_of_domain']} row(s) outside the "
                              f"declared applicability domain and policy='reject'")
        return {
            "model_id": self.model_id,
            "version": self.version,
            "outputs": np.asarray(Y).tolist(),
            "columns": self.output_names,
            "out_of_domain": violations,
            "policy": policy,
        }

    # -- applicability domain --------------------------------------------- #
    def domain_violations(self, inputs: Any) -> dict:
        import numpy as np

        X = np.asarray(inputs, dtype=float)
        if X.ndim == 1:
            X = X[None, :]
        bounds = self.manifest["applicability_domain"].get("bounds", {}) or {}
        named = {b for b in bounds if b not in {self.input_spec.get("name")}}
        if named:
            raise LoaderError("applicability_domain.bounds only supports the declared input "
                              f"name componentwise; unsupported keys: {sorted(named)}")
        rng = bounds.get(self.input_spec.get("name"))
        if not rng:
            return {"n_out_of_domain": 0, "rows": [], "bounds": None}
        lo, hi = float(rng[0]), float(rng[1])
        mask = (X < lo - 1e-12) | (X > hi + 1e-12)
        rows = np.nonzero(mask.any(axis=1))[0].tolist()
        return {
            "n_out_of_domain": len(rows),
            "rows": rows[:20],
            "bounds": [lo, hi],
            "per_column": mask.sum(axis=0).tolist(),
        }


def _width(spec: Mapping[str, Any]) -> int:
    shape = spec.get("shape") or []
    dims = [d for d in shape if isinstance(d, int)]
    if not dims:
        raise LoaderError(f"input/output spec {spec.get('name')!r} has no concrete width: {shape}")
    return dims[-1]


def _preproc(manifest: Mapping[str, Any]) -> dict:
    pre = manifest["io_contract"].get("preprocessing") or {}
    return {
        "input_center": pre.get("input_center"),
        "input_scale": pre.get("input_scale"),
        "output_center": pre.get("output_center"),
        "output_scale": pre.get("output_scale"),
    }


def _apply(X, center, scale):
    import numpy as np

    if center is None or scale is None:
        return X
    return (X - np.asarray(center, float)) / np.asarray(scale, float)


def _forward_numpy_affine(model_dir: Path, manifest: Mapping[str, Any]):
    import numpy as np

    weights_rel = next(a["path"] for a in manifest["artifacts"] if a["role"] == "weights")
    data = np.load(model_dir / weights_rel)
    W, b = data["W"], data["b"]
    pre = _preproc(manifest)

    def forward(X):
        Z = _apply(X, pre["input_center"], pre["input_scale"]) @ W.T + b
        if pre["output_center"] is not None and pre["output_scale"] is not None:
            Z = Z * np.asarray(pre["output_scale"], float) + np.asarray(pre["output_center"], float)
        return Z

    return forward


def _forward_torch_mlp(model_dir: Path, manifest: Mapping[str, Any]):
    import torch

    params = manifest["io_contract"]["loader"]
    layers = [int(w) for w in params["layers"]]
    act_name = params.get("activation", "gelu")
    if act_name not in _ACTIVATIONS:
        raise LoaderError(f"unsupported activation {act_name!r}")
    weights_rel = next(a["path"] for a in manifest["artifacts"] if a["role"] == "weights")
    payload = torch.load(model_dir / weights_rel, map_location="cpu", weights_only=True)
    state = payload["state_dict"] if "state_dict" in payload else payload
    modules: list[Any] = []
    act_cls = {"relu": torch.nn.ReLU, "gelu": torch.nn.GELU, "tanh": torch.nn.Tanh,
               "silu": torch.nn.SiLU, "none": torch.nn.Identity}[act_name]
    for i, (fan_in, fan_out) in enumerate(zip(layers[:-1], layers[1:])):
        modules.append(torch.nn.Linear(fan_in, fan_out))
        if i < len(layers) - 2:
            modules.append(act_cls())
    net = torch.nn.Sequential(*modules)
    net.load_state_dict(state)
    net.eval()
    pre = _preproc(manifest)

    def forward(X):
        import numpy as np

        Z = _apply(np.asarray(X, float), pre["input_center"], pre["input_scale"])
        with torch.no_grad():
            out = net(torch.as_tensor(Z, dtype=torch.float32)).numpy().astype(float)
        if pre["output_center"] is not None and pre["output_scale"] is not None:
            out = out * np.asarray(pre["output_scale"], float) + np.asarray(pre["output_center"], float)
        return out

    return forward


_FORWARDERS = {
    "numpy-affine": _forward_numpy_affine,
    "torch-mlp": _forward_torch_mlp,
}


def load_model(registry: ModelRegistry | str | Path | None, model_id: str,
               version: str | None = None) -> Predictor:
    """Load a registered model by identity; the manifest declares how."""
    reg = registry if isinstance(registry, ModelRegistry) else ModelRegistry(registry)
    manifest = reg.load_manifest(model_id, version)
    kind = manifest["io_contract"]["loader"].get("kind")
    if kind not in _FORWARDERS:
        raise LoaderError(f"unknown loader kind {kind!r}; known: {sorted(_FORWARDERS)}")
    model_dir = reg.model_dir(manifest["model_id"], manifest["version"])
    forward = _FORWARDERS[kind](model_dir, manifest)
    return Predictor(manifest, model_dir, forward)