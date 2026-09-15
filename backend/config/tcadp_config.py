import logging
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class TCADPConfig(BaseSettings):
    """
    Configuration settings for TCADP
    """
    TC_SECRET_APPID: str = Field(
        description="Tencent secret appid, you can obtain it from https://console.cloud.tencent.com/cam/capi",
        default="",
    )

    TC_SECRET_ID: str = Field(
        description="Tencent secret id, you can obtain it from https://console.cloud.tencent.com/cam/capi",
        default="",
    )

    TC_SECRET_KEY: str = Field(
        description="Tencent secret key, you can obtain it from https://console.cloud.tencent.com/cam/capi",
        default="",
    )

    ADP_SECRET_ID: str = Field(
        description="ADP secret id, used when ServiceVendor is ChinaTencentADP. Falls back to TC_SECRET_ID if empty.",
        default="",
    )

    ADP_SECRET_KEY: str = Field(
        description="ADP secret key, used when ServiceVendor is ChinaTencentADP. Falls back to TC_SECRET_KEY if empty.",
        default="",
    )

    ADP_VISITOR_ID_TYPE: Literal["CUSTOMER_ID", "NAME"] = Field(
        description="VisitorId type for ADP chat requests. Supported values: CUSTOMER_ID, NAME",
        default="NAME",
    )

    ADP_AGENT_CONFIGS: list[dict] = Field(
        description=(
            "Server-side ADP Agent mappings. Each item must contain agentId and applicationId; "
            "an empty list keeps the local controlled provider enabled."
        ),
        default_factory=list,
    )

    ADP_DEFAULT_AGENT_ID: str = Field(
        description=(
            "Server-selected default Agent ID. Required when ADP_AGENT_CONFIGS contains more "
            "than one mapping; never taken from a client request."
        ),
        default="",
        max_length=128,
    )

    TC_CANARY_HEADER: str = Field(
        description=(
            "Global default for the X-TC-Canary header on ALL forwarded TC API requests "
            "(e.g. 'toe-test-4130'), so switching the canary cluster only requires editing "
            "this env var. Priority: per-action 'headers.X-TC-Canary' in action_version/*.json "
            "> this env value > not sent. Leave empty to not send the header at all "
            "(all static canary entries have been removed from action_version/*.json)."
        ),
        default="",
    )

    # M3 is disabled by default. The deterministic fixture is enabled only
    # with an explicit setting; production never silently falls back.
    M3_USE_MOCK: bool = Field(default=False)
    M3_BASE_URL: str = Field(default="")
    M3_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)

    PLATFORM_CHANNEL_CREDENTIAL_KEY: str = Field(
        description=(
            "Fernet key used to encrypt channel credentials. This must be supplied "
            "through the deployment secret store; an empty value disables credential operations."
        ),
        default="",
    )

    PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION: str = Field(
        description="Active channel credential encryption key version.",
        default="v1",
        min_length=1,
        max_length=64,
    )

    PLATFORM_CHANNEL_CREDENTIAL_KEY_RING: dict[str, str] = Field(
        description="Optional old Fernet keys keyed by version for controlled decryption during key rotation.",
        default_factory=dict,
    )

    ADP_TOOL_SERVICE_TOKEN: str = Field(
        description=(
            "High-entropy service token required by legacy internal ADP execution and inbound routes; shipment tools use Admin API keys. "
            "Leave empty to keep those routes disabled."
        ),
        default="",
    )

    PLATFORM_PUBLIC_BASE_URL: str = Field(
        description=(
            "Public HTTPS origin of the customer portal, used to build links a "
            "channel message can open (for example a WeChat rich card). Leave "
            "empty to disable link-bearing messages instead of emitting a "
            "localhost URL a customer cannot open."
        ),
        default="",
        max_length=255,
    )

    PLATFORM_SHARED_RESULT_TTL_DAYS: int = Field(
        description=(
            "Lifetime, in days, of a no-login channel result share link. 0 (the "
            "default) means the link never expires: the rich card stays in the "
            "customer's chat history forever, so access is bounded by revocation "
            "(account disable / identity unbind) rather than a clock. A positive "
            "value opts into a fixed expiry window instead."
        ),
        default=0,
        ge=0,
    )

    PLATFORM_CHANNEL_SERVICE_TOKEN: str = Field(
        description=(
            "High-entropy service token required by trusted channel adapters to confirm "
            "a browser-started channel identity binding. Leave empty to disable confirmation."
        ),
        default="",
    )

    ADP_EXECUTION_CONTEXT_TTL_SECONDS: int = Field(
        description="Lifetime of an ADP execution context in seconds.",
        default=300,
        ge=30,
        le=900,
    )
