"""System, data-location, and self-host setup routes."""

from __future__ import annotations

import hashlib
from ipaddress import ip_address
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.api.deps import SessionUser
from app.config import get_settings
from app.core.data_ownership import ARTIFACT_OWNERSHIP, DATA_OWNERSHIP, ownership_map_response

router = APIRouter(prefix="/system", tags=["system"])
self_host_router = APIRouter(prefix="/self-host", tags=["self-host"])


class SystemInfoResponse(BaseModel):
    app_name: str
    deployment_mode: str
    public_base_url: str
    cloud_base_url: str
    mcp_url: str
    git_sha: str | None
    git_dirty: bool
    audio_retention_policy: str
    self_hosting_available: bool
    billing_mode: str


class ProvisionStep(BaseModel):
    id: str
    label: str
    status: Literal["pending", "manual_review_required", "blocked"]


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(validate_default=True)

    hostname: str | None = Field(default=None, max_length=253)
    vps_ip: str = Field(min_length=3, max_length=64)
    ssh_username: str = Field(default="root", min_length=1, max_length=64)
    auth_method: Literal["ssh_key", "password"]
    ssh_public_key: str | None = Field(default=None, max_length=4096)
    ssh_password: str | None = Field(default=None)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().rstrip(".")
        if not normalized:
            return None
        if len(normalized) < 3:
            raise ValueError("hostname must be a valid DNS name")
        labels = normalized.split(".")
        if any(not label or len(label) > 63 for label in labels):
            raise ValueError("hostname must be a valid DNS name")
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
        for label in labels:
            if label[0] == "-" or label[-1] == "-" or any(ch not in allowed for ch in label):
                raise ValueError("hostname must be a valid DNS name")
        return normalized

    @field_validator("vps_ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        return str(ip_address(value.strip()))

    @field_validator("ssh_username")
    @classmethod
    def validate_ssh_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("ssh_username is required")
        return normalized

    @field_validator("ssh_public_key")
    @classmethod
    def validate_public_key(cls, value: str | None, info: ValidationInfo) -> str | None:
        auth_method = info.data.get("auth_method")
        if value is None:
            if auth_method == "ssh_key":
                raise ValueError("ssh_public_key is required for ssh_key auth")
            return None
        normalized = value.strip()
        if not normalized:
            if auth_method == "ssh_key":
                raise ValueError("ssh_public_key is required for ssh_key auth")
            return None
        if not (
            normalized.startswith("ssh-ed25519 ")
            or normalized.startswith("ssh-rsa ")
            or normalized.startswith("ecdsa-sha2-")
        ):
            raise ValueError("ssh_public_key must be an OpenSSH public key")
        return normalized

    @field_validator("ssh_password")
    @classmethod
    def validate_password(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("auth_method") != "password":
            return None
        if not (value or "").strip():
            raise ValueError("ssh_password is required for password auth")
        return value


class ProvisionResponse(BaseModel):
    job_id: str
    status: Literal["manual_review_required"]
    hostname: str | None
    vps_ip: str
    steps: list[ProvisionStep]
    message: str


class MigrationPreflightResponse(BaseModel):
    status: Literal["ready"]
    owned_exportable: list[str]
    reconnect_required: list[str]
    server_local: list[str]
    excluded: list[str]
    data_map: dict[str, object]


@router.get("/info", response_model=SystemInfoResponse)
async def system_info() -> SystemInfoResponse:
    settings = get_settings()
    public_base_url = settings.public_base_url_resolved
    return SystemInfoResponse(
        app_name=settings.app_name,
        deployment_mode=settings.deployment_mode,
        public_base_url=public_base_url,
        cloud_base_url=settings.cloud_base_url.rstrip("/"),
        mcp_url=settings.mcp_resource_url_resolved,
        git_sha=settings.git_sha,
        git_dirty=settings.git_dirty,
        audio_retention_policy="delete_after_processing",
        self_hosting_available=True,
        billing_mode="cloud" if settings.deployment_mode == "wai_cloud" else "self_host",
    )


@router.get("/data-map")
async def data_map() -> dict[str, object]:
    return ownership_map_response()


@self_host_router.get("/migration/preflight", response_model=MigrationPreflightResponse)
async def migration_preflight(user: SessionUser) -> MigrationPreflightResponse:
    entries = [*DATA_OWNERSHIP, *ARTIFACT_OWNERSHIP]
    return MigrationPreflightResponse(
        status="ready",
        owned_exportable=[
            entry.name for entry in entries if entry.classification == "owned_exportable"
        ],
        reconnect_required=[
            entry.name for entry in entries if entry.classification == "reconnect_required"
        ],
        server_local=[entry.name for entry in entries if entry.classification == "self_host_local"],
        excluded=[
            entry.name
            for entry in entries
            if entry.classification in {"hosted_control_plane", "excluded_with_reason"}
        ],
        data_map=ownership_map_response(),
    )


@self_host_router.post(
    "/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_provisioning(
    payload: ProvisionRequest,
    user: SessionUser,
) -> ProvisionResponse:
    """Validate a self-host request and expose the required setup checklist.

    The SSH executor is deliberately not faked. Until the executor is wired,
    the API returns an explicit manual-review status that the UI can surface.
    """
    fingerprint = hashlib.sha256(
        f"{user.id}:{payload.hostname or ''}:{payload.vps_ip}".encode("utf-8")
    ).hexdigest()[:24]
    steps = [
        ProvisionStep(
            id="validate_inputs",
            label="Validate VPS address and SSH access",
            status="manual_review_required",
        ),
        ProvisionStep(
            id="create_deploy_user", label="Create a non-root deploy user", status="pending"
        ),
        ProvisionStep(
            id="install_runtime",
            label="Install Docker, Compose, and WaiComputer services",
            status="pending",
        ),
        ProvisionStep(
            id="configure_firewall",
            label="Allow SSH, HTTP, and HTTPS only",
            status="pending",
        ),
        ProvisionStep(
            id="configure_dns_https",
            label="Connect optional domain and issue HTTPS certificate",
            status="pending",
        ),
        ProvisionStep(
            id="verify_health", label="Verify WaiComputer health checks", status="pending"
        ),
        ProvisionStep(
            id="remove_bootstrap_access",
            label="Remove temporary root/password bootstrap access",
            status="pending",
        ),
    ]
    return ProvisionResponse(
        job_id=f"selfhost_{fingerprint}",
        status="manual_review_required",
        hostname=payload.hostname,
        vps_ip=payload.vps_ip,
        steps=steps,
        message=(
            "Provisioning inputs are valid. Automated SSH execution is not enabled "
            "in this build, so no server changes were made."
        ),
    )
