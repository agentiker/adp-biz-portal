"""Persistence models for the unified business platform.

The legacy chat tables intentionally remain separate.  Platform identity and
authorization use their own tables so a customer account can be introduced
without changing the assumptions made by the existing ADP compatibility APIs.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    UUID,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from model.base import Base


class PlatformRole(enum.StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"
    OPS = "ops"


class PlatformStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    SUSPENDED = "suspended"


class EnterpriseStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class IntegrationConnectionStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PlatformChannelCredentialStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PlatformChannelIdentityStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PlatformEnterprise(Base):
    __tablename__ = "platform_enterprise"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    Name = Column(String(255), nullable=False)
    CustomerCode = Column(String(128), nullable=False, unique=True, index=True)
    UnifiedSocialCreditCode = Column(String(32), nullable=True)
    ContactPerson = Column(String(128), nullable=True)
    ContactPhone = Column(String(32), nullable=True)
    Status = Column(String(16), nullable=False, server_default=EnterpriseStatus.ACTIVE)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    ExtraInfo = Column(Text(), nullable=True)


class IntegrationConnection(Base):
    """Server-owned mapping from a configured legacy app to an upstream vendor."""

    __tablename__ = "integration_connection"
    __table_args__ = (
        UniqueConstraint("ApplicationId", name="unique_integration_application"),
        Index("idx_integration_connection_status", "Status"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ApplicationId = Column(String(64), nullable=False)
    UpstreamAppId = Column(String(255), nullable=False)
    Vendor = Column(String(64), nullable=False)
    Status = Column(String(16), nullable=False, server_default=IntegrationConnectionStatus.ACTIVE)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class EnterpriseExternalAccount(Base):
    """Enterprise-scoped upstream account and workspace binding."""

    __tablename__ = "enterprise_external_account"
    __table_args__ = (
        UniqueConstraint("EnterpriseId", "ConnectionId", name="unique_enterprise_connection"),
        UniqueConstraint("ConnectionId", "WorkspaceId", name="unique_connection_workspace"),
        Index("idx_external_account_enterprise_status", "EnterpriseId", "Status"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    ConnectionId = Column(UUID(), ForeignKey("integration_connection.Id", ondelete="CASCADE"), nullable=False, index=True)
    ExternalAccountId = Column(String(255), nullable=False)
    WorkspaceId = Column(String(255), nullable=False)
    Status = Column(String(16), nullable=False, server_default=IntegrationConnectionStatus.ACTIVE)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformChannelCredential(Base):
    """Encrypted platform channel secret.

    ``Ciphertext`` is intentionally not exposed by any serializer. The worker
    is the only caller allowed to use the decryption helper in
    ``core.channel_credentials``. Enterprise and connection columns remain
    nullable for compatibility with pre-platform-channel deployments; new
    channel instances are platform-owned and leave both columns empty.
    """

    __tablename__ = "platform_channel_credential"
    __table_args__ = (
        UniqueConstraint(
            "Channel",
            "ChannelInstanceId",
            name="unique_platform_channel_credential",
        ),
        Index("idx_platform_channel_credential_status", "Status"),
        Index("idx_platform_channel_credential_lookup", "Channel", "ChannelInstanceId", "Status"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="SET NULL"), nullable=True, index=True)
    ConnectionId = Column(UUID(), ForeignKey("integration_connection.Id", ondelete="SET NULL"), nullable=True, index=True)
    Channel = Column(String(48), nullable=False)
    ChannelInstanceId = Column(String(128), nullable=False)
    Ciphertext = Column(Text(), nullable=False)
    KeyVersion = Column(String(64), nullable=False)
    Version = Column(Integer, nullable=False, server_default=text("1"))
    Fingerprint = Column(String(64), nullable=False)
    Status = Column(String(16), nullable=False, server_default=PlatformChannelCredentialStatus.ACTIVE, index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    RotatedAt = Column(DateTime, nullable=True)
    ExpiresAt = Column(DateTime, nullable=True)


class PlatformChannelIdentity(Base):
    """A server-owned binding between one platform user and a channel identity.

    The one-time state is stored only as a digest. ``ExternalIdentityId`` is
    supplied by a trusted channel adapter during confirmation, never inferred
    from a message body. Enterprise authorization is deliberately absent from
    the binding and is resolved from current memberships for every execution.
    """

    __tablename__ = "platform_channel_identity"
    __table_args__ = (
        Index("idx_platform_channel_identity_user", "UserId", "Status"),
        Index("idx_platform_channel_identity_external", "Channel", "ChannelInstanceId", "ExternalIdentityId", "Status"),
        Index("idx_platform_channel_identity_pending", "StateHash", "StateExpiresAt"),
        # One external identity may map to at most one active platform user.
        # The database enforces it so two concurrent confirmations cannot both
        # win; application checks alone leave a race window.
        Index(
            "uq_platform_channel_identity_active",
            "Channel",
            "ChannelInstanceId",
            "ExternalIdentityId",
            unique=True,
            postgresql_where=text(f"\"Status\" = '{PlatformChannelIdentityStatus.ACTIVE}'"),
        ),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    UserId = Column(UUID(), ForeignKey("platform_user.Id", ondelete="CASCADE"), nullable=False, index=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    # Channel identity is a platform-user binding. Enterprise scope is
    # resolved at message execution time from the user's active memberships.
    # Keep this nullable for backwards-compatible legacy rows; new bindings
    # never populate it.
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="SET NULL"), nullable=True, index=True)
    Channel = Column(String(48), nullable=False)
    ChannelInstanceId = Column(String(128), nullable=False)
    # Null while a binding waits for the original channel sender to confirm.
    # The browser often cannot learn its own external identity (for example a
    # WeChat OpenID without web authorization), so the trusted channel adapter
    # supplies it at confirmation time. An active row always carries a value.
    ExternalIdentityId = Column(String(255), nullable=True)
    Status = Column(String(16), nullable=False, server_default=PlatformChannelIdentityStatus.PENDING, index=True)
    StateHash = Column(String(64), nullable=True, unique=True)
    StateExpiresAt = Column(DateTime, nullable=True)
    ConfirmedAt = Column(DateTime, nullable=True)
    RevokedAt = Column(DateTime, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformUser(Base):
    __tablename__ = "platform_user"
    __table_args__ = (UniqueConstraint("AccountId", name="unique_platform_account"),)

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    Name = Column(String(255), nullable=False)
    PhoneNormalized = Column(String(32), nullable=False, unique=True, index=True)
    PhoneMasked = Column(String(32), nullable=False)
    Role = Column(String(16), nullable=False, server_default=PlatformRole.CUSTOMER)
    Status = Column(String(16), nullable=False, server_default=PlatformStatus.ACTIVE)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformMembership(Base):
    __tablename__ = "platform_membership"
    __table_args__ = (
        UniqueConstraint("UserId", "EnterpriseId", name="unique_platform_membership"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    UserId = Column(UUID(), ForeignKey("platform_user.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    MembershipRole = Column(String(16), nullable=False, server_default=PlatformRole.CUSTOMER)
    Active = Column(Boolean, nullable=False, server_default=text("true"))
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformCredential(Base):
    __tablename__ = "platform_credential"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    PasswordHash = Column(String(255), nullable=False)
    PasswordSalt = Column(String(255), nullable=False)
    FailedAttempts = Column(Integer, nullable=False, server_default=text("0"))
    LockedUntil = Column(DateTime, nullable=True)
    MustReset = Column(Boolean, nullable=False, server_default=text("false"))
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformAuthSession(Base):
    __tablename__ = "platform_auth_session"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    TokenId = Column(String(64), nullable=False, unique=True, index=True)
    ExpiresAt = Column(DateTime, nullable=False, index=True)
    RevokedAt = Column(DateTime, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    LastSeenAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformConversation(Base):
    __tablename__ = "platform_conversation"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    Channel = Column(String(32), nullable=False, server_default="web")
    Title = Column(String(255), nullable=False)
    LastActiveAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformMessage(Base):
    """Auditable messages that make a web conversation recoverable."""

    __tablename__ = "platform_message"
    __table_args__ = (
        Index("idx_platform_message_conversation", "ConversationId", "CreatedAt"),
        Index("idx_platform_message_account", "AccountId", "CreatedAt"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ConversationId = Column(UUID(), ForeignKey("platform_conversation.Id", ondelete="CASCADE"), nullable=False, index=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    ExecutionRunId = Column(UUID(), ForeignKey("platform_execution_run.Id", ondelete="SET NULL"), nullable=True, index=True)
    Direction = Column(String(16), nullable=False)
    MessageType = Column(String(32), nullable=False, server_default="text")
    Body = Column(Text(), nullable=True)
    Payload = Column(JSON, nullable=False, default=dict)
    TraceId = Column(String(64), nullable=False, index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)


class PlatformExecutionRun(Base):
    """One durable business query execution and its controlled summary."""

    __tablename__ = "platform_execution_run"
    __table_args__ = (
        UniqueConstraint("RunId", name="unique_platform_execution_run"),
        Index("idx_platform_execution_run_conversation", "ConversationId", "StartedAt"),
        Index("idx_platform_execution_run_account", "AccountId", "StartedAt"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ConversationId = Column(UUID(), ForeignKey("platform_conversation.Id", ondelete="CASCADE"), nullable=False, index=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    RunId = Column(String(64), nullable=False, unique=True, index=True)
    Query = Column(String(128), nullable=False)
    Status = Column(String(32), nullable=False, server_default="running", index=True)
    Title = Column(String(255), nullable=False, server_default="业务查询")
    Summary = Column(Text(), nullable=False, server_default="")
    TraceId = Column(String(64), nullable=False, index=True)
    StartedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    CompletedAt = Column(DateTime, nullable=True)


class PlatformEvidence(Base):
    """Allow-listed evidence captured by an execution run."""

    __tablename__ = "platform_evidence"
    __table_args__ = (
        UniqueConstraint("ExecutionRunId", "Label", name="unique_platform_evidence_label"),
        Index("idx_platform_evidence_run", "ExecutionRunId", "CapturedAt"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ExecutionRunId = Column(UUID(), ForeignKey("platform_execution_run.Id", ondelete="CASCADE"), nullable=False, index=True)
    ConversationId = Column(UUID(), ForeignKey("platform_conversation.Id", ondelete="CASCADE"), nullable=False, index=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    Label = Column(String(128), nullable=False)
    Value = Column(Text(), nullable=False)
    Source = Column(String(255), nullable=False)
    CapturedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    Known = Column(Boolean, nullable=False, server_default=text("false"))


class PlatformInboundMessage(Base):
    """Normalized inbound message envelope with channel-level deduplication."""

    __tablename__ = "platform_inbound_message"
    __table_args__ = (
        UniqueConstraint(
            "ChannelInstanceId",
            "ExternalMessageId",
            name="unique_platform_inbound_message",
        ),
        Index("idx_platform_inbound_conversation", "ChannelInstanceId", "ExternalConversationId"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ChannelInstanceId = Column(String(128), nullable=False)
    ExternalMessageId = Column(String(255), nullable=False)
    ExternalConversationId = Column(String(255), nullable=False)
    SenderIdentityId = Column(String(255), nullable=False)
    MessageType = Column(String(32), nullable=False, server_default="text")
    Text = Column(Text(), nullable=True)
    Payload = Column(JSON, nullable=False, default=dict)
    TraceId = Column(String(64), nullable=False, index=True)
    Status = Column(String(24), nullable=False, server_default="accepted", index=True)
    ReceivedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    # Latest moment this channel still accepts a reply for this message. Null
    # when the channel has no protocol deadline (for example the web portal,
    # which is read back by the browser instead of pushed).
    ReplyWindowExpiresAt = Column(DateTime, nullable=True)


class PlatformChannelReplayMarker(Base):
    """Cross-instance replay markers for signed channel callbacks.

    A signature that was already accepted must not be accepted again by any
    API instance, so the marker is stored in the database instead of process
    memory. Rows expire with the channel's replay window and are pruned
    opportunistically; the unique constraint is what actually rejects a replay.
    """

    __tablename__ = "platform_channel_replay_marker"
    __table_args__ = (
        UniqueConstraint(
            "Channel",
            "ChannelInstanceId",
            "ReplayKey",
            name="unique_platform_channel_replay",
        ),
        Index("idx_platform_channel_replay_expires", "ExpiresAt"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    Channel = Column(String(48), nullable=False)
    ChannelInstanceId = Column(String(128), nullable=False)
    ReplayKey = Column(String(64), nullable=False)
    ExpiresAt = Column(DateTime, nullable=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformSharedResult(Base):
    """A no-login, read-only share link for one channel query result.

    A channel reply too long for a chat bubble links to a rendered result page
    that must open without a portal login, so access is a high-entropy bearer
    token stored only as its SHA-256 digest. Each row is scoped to a single
    execution run, expires, and is revoked when the owning account is disabled
    or the channel identity is unbound.
    """

    __tablename__ = "platform_shared_result"
    __table_args__ = (
        Index("idx_platform_shared_result_expires", "ExpiresAt"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    TokenHash = Column(String(64), nullable=False, unique=True, index=True)
    ExecutionRunId = Column(UUID(), ForeignKey("platform_execution_run.Id", ondelete="CASCADE"), nullable=False, index=True)
    ConversationId = Column(UUID(), nullable=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), nullable=True)
    Channel = Column(String(48), nullable=False)
    ChannelInstanceId = Column(String(128), nullable=False)
    # NULL means the link never expires: the card stays in the customer's chat
    # history forever, so access is bounded by revocation, not a clock.
    ExpiresAt = Column(DateTime, nullable=True)
    RevokedAt = Column(DateTime, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    LastAccessedAt = Column(DateTime, nullable=True)


class PlatformChannelCursor(Base):
    """Durable sync cursor for pull-based channels (WeChat 客服 sync_msg).

    A channel that delivers messages by cursor pagination (not by pushing each
    message in the callback) must persist the position across API instances and
    process restarts. The next_cursor is stored BEFORE dispatching a page so a
    crash never re-reads and re-dispatches an already-processed page; message
    idempotency is a separate guard by external message id.
    """

    __tablename__ = "platform_channel_cursor"
    __table_args__ = (
        UniqueConstraint(
            "Channel",
            "ChannelInstanceId",
            "ScopeId",
            name="unique_platform_channel_cursor",
        ),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    Channel = Column(String(48), nullable=False)
    ChannelInstanceId = Column(String(128), nullable=False)
    # Sub-scope within the instance (e.g. WeChat 客服 open_kfid); "all" when none.
    ScopeId = Column(String(128), nullable=False)
    Cursor = Column(String(1024), nullable=False, server_default="")
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformDeliveryTask(Base):
    """Durable task queue row used by API and channel workers.

    A unique deduplication key makes repeated provider callbacks harmless. A
    conversation key lets the worker serialize one conversation while still
    processing unrelated conversations concurrently.
    """

    __tablename__ = "platform_delivery_task"
    __table_args__ = (
        UniqueConstraint("DeduplicationKey", name="unique_platform_delivery_dedup"),
        Index("idx_platform_delivery_ready", "Status", "AvailableAt", "LeaseUntil"),
        Index("idx_platform_delivery_conversation", "ConversationKey", "Status"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    TaskType = Column(String(64), nullable=False, index=True)
    DeduplicationKey = Column(String(255), nullable=False)
    ConversationKey = Column(String(255), nullable=True)
    Payload = Column(JSON, nullable=False, default=dict)
    Status = Column(String(24), nullable=False, server_default="queued", index=True)
    Attempts = Column(Integer, nullable=False, server_default=text("0"))
    MaxAttempts = Column(Integer, nullable=False, server_default=text("5"))
    AvailableAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    LeaseOwner = Column(String(128), nullable=True)
    LeaseUntil = Column(DateTime, nullable=True, index=True)
    LastError = Column(Text(), nullable=True)
    Result = Column(JSON, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    CompletedAt = Column(DateTime, nullable=True)


class PlatformToolDefinition(Base):
    __tablename__ = "platform_tool_definition"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    Name = Column(String(128), nullable=False, unique=True)
    Version = Column(String(32), nullable=False)
    Permission = Column(String(128), nullable=False)
    Enabled = Column(Boolean, nullable=False, server_default=text("true"))
    ReadOnly = Column(Boolean, nullable=False, server_default=text("true"))
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PlatformExecutionContext(Base):
    """Short-lived, server-issued scope passed to an ADP tool execution.

    The raw token is returned only at issuance time. The database stores its
    SHA-256 digest, so a database read cannot be used as a bearer credential.
    """

    __tablename__ = "platform_execution_context"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    TokenHash = Column(String(64), nullable=False, unique=True, index=True)
    UserId = Column(UUID(), ForeignKey("platform_user.Id", ondelete="CASCADE"), nullable=False, index=True)
    AccountId = Column(UUID(), ForeignKey("account.Id", ondelete="CASCADE"), nullable=False, index=True)
    EnterpriseId = Column(UUID(), ForeignKey("platform_enterprise.Id", ondelete="CASCADE"), nullable=False, index=True)
    # Null for channel-originated executions. A browser message authorizes
    # through its login session, while a channel message authorizes through a
    # confirmed channel identity plus the memberships resolved for that
    # message. Account-wide revocation invalidates both (see
    # ``revoke_account_execution_contexts``).
    PlatformSessionId = Column(UUID(), ForeignKey("platform_auth_session.Id", ondelete="CASCADE"), nullable=True, index=True)
    ConversationId = Column(UUID(), ForeignKey("platform_conversation.Id", ondelete="CASCADE"), nullable=True, index=True)
    AgentId = Column(String(128), nullable=False)
    Channel = Column(String(32), nullable=False)
    RunId = Column(String(64), nullable=False, index=True)
    PermissionVersion = Column(String(128), nullable=False)
    ExpiresAt = Column(DateTime, nullable=False, index=True)
    RevokedAt = Column(DateTime, nullable=True, index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformToolCall(Base):
    """Request claim and evidence summary for an ADP tool call."""

    __tablename__ = "platform_tool_call"
    __table_args__ = (
        UniqueConstraint("ExecutionContextId", "RequestId", name="unique_platform_tool_request"),
    )

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ExecutionContextId = Column(UUID(), ForeignKey("platform_execution_context.Id", ondelete="CASCADE"), nullable=False, index=True)
    ToolName = Column(String(128), nullable=False)
    RequestId = Column(String(128), nullable=False)
    QueryHash = Column(String(64), nullable=True)
    TraceId = Column(String(64), nullable=False, index=True)
    Status = Column(String(32), nullable=False, server_default="started")
    Outcome = Column(String(64), nullable=True)
    Evidence = Column(JSON, nullable=True)
    StartedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    CompletedAt = Column(DateTime, nullable=True)


class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_event"

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    ActorAccountId = Column(UUID(), ForeignKey("account.Id", ondelete="SET NULL"), nullable=True, index=True)
    Action = Column(String(128), nullable=False, index=True)
    TargetType = Column(String(64), nullable=False)
    TargetId = Column(String(128), nullable=True)
    TraceId = Column(String(64), nullable=False, index=True)
    Outcome = Column(String(32), nullable=False, server_default="success")
    Metadata = Column(JSON, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)


class PlatformSchemaVersion(Base):
    """Compatibility marker retained for installations created before v5."""

    __tablename__ = "platform_schema_version"

    Version: Mapped[int] = mapped_column(Integer, primary_key=True)
    AppliedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PlatformMigration(Base):
    """Auditable state for each explicit database migration revision."""

    __tablename__ = "platform_migration"

    Version: Mapped[int] = mapped_column(Integer, primary_key=True)
    Name = Column(String(128), nullable=False)
    Checksum = Column(String(64), nullable=False)
    Status = Column(String(16), nullable=False, server_default="applied", index=True)
    AppliedBy = Column(String(128), nullable=False, server_default="migration-cli")
    AppliedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    RolledBackAt = Column(DateTime, nullable=True)


class PlatformConfigVersion(Base):
    """Versioned platform configuration with an auditable publish lifecycle."""

    __tablename__ = "platform_config_version"
    __table_args__ = (UniqueConstraint("Version", name="unique_platform_config_version"),)

    Id: Mapped[str] = mapped_column(UUID(), server_default=text("uuid_generate_v4()"), primary_key=True)
    Version = Column(Integer, nullable=False, index=True)
    Status = Column(String(16), nullable=False, server_default="draft", index=True)
    Payload = Column(JSON, nullable=False)
    ValidationErrors = Column(JSON, nullable=False, default=list)
    CreatedByAccountId = Column(UUID(), ForeignKey("account.Id", ondelete="SET NULL"), nullable=True, index=True)
    PublishedByAccountId = Column(UUID(), ForeignKey("account.Id", ondelete="SET NULL"), nullable=True, index=True)
    RolledBackByAccountId = Column(UUID(), ForeignKey("account.Id", ondelete="SET NULL"), nullable=True, index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), index=True)
    UpdatedAt = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    PublishedAt = Column(DateTime, nullable=True)
    RolledBackAt = Column(DateTime, nullable=True)
    RollbackSourceVersion = Column(Integer, nullable=True)
