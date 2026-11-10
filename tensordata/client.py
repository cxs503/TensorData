"""Small synchronous client for TensorData's stable HTTP API."""

from typing import Any, Self

import httpx


class TensorDataAPIError(RuntimeError):
    """Raised when TensorData returns a non-success HTTP response."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"TensorData API returned HTTP {status_code}: {detail}")


class TensorDataClient:
    """Agent-friendly client for registering, validating and assembling data."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if not response.is_success:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise TensorDataAPIError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/assets", json=payload)

    def upload_artifact(
        self,
        asset_id: str,
        filename: str,
        content: bytes,
        *,
        media_type: str = "application/octet-stream",
        role: str = "raw",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/assets/{asset_id}/artifacts",
            params={"role": role},
            files={"file": (filename, content, media_type)},
        )

    def run_quality_checks(
        self,
        artifact_id: str,
        *,
        profile: str = "general",
        executed_by: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/artifacts/{artifact_id}/quality-checks",
            json={"profile": profile, "executed_by": executed_by},
        )

    def list_quality_reports(self, artifact_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/artifacts/{artifact_id}/quality-reports")

    def create_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/datasets", json=payload)

    def create_dataset_version(
        self, dataset_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/api/v1/datasets/{dataset_id}/versions", json=payload
        )

    def create_provenance(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/provenance", json=payload)

    def get_artifact_lineage(self, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/lineage/artifacts/{artifact_id}")
