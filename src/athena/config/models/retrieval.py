"""Retrieval provider, embeddings, scoping, search, and offload configuration models."""

from __future__ import annotations

from pydantic import Field

from athena.config.models.base import AthenaConfigModel, non_reloadable_field


class RetrievalProviderConfig(AthenaConfigModel):
    """Retrieval backend service configuration."""

    kind: str = "openviking"
    base_url: str = "http://openviking:8000"
    timeout_s: float = 60.0


class EmbeddingConfig(AthenaConfigModel):
    """Vector embedding model and dimension settings."""

    base_url: str = "http://athena-ml:8082/v1"
    model: str = non_reloadable_field()
    dimension: int = non_reloadable_field(default=1024)


class ScopesConfig(AthenaConfigModel):
    """Resource scope mapping and date-scoping thresholds."""

    vault_root: str = "viking://resources/vault"
    email_root: str = "viking://resources/email"
    calendar_root: str = "viking://resources/calendar"
    max_month_scopes: int = 6
    allow_unscoped_search: bool = True


class SearchConfig(AthenaConfigModel):
    """Candidate recall and final selection counts."""

    candidates: int = 40
    final_k: int = 8


class OffloadConfig(AthenaConfigModel):
    """Offload directory and preview caps for I-09 compliance."""

    directory: str = "/retrieved"
    preview_chars: int = 200
    max_result_tokens: int = 1500


class IndexCatchupConfig(AthenaConfigModel):
    """Nightly re-indexing and catch-up batch settings."""

    catchup_batch_size: int = 50
    submit_timeout_s: float = 300.0
    retry_max: int = 3


class RetrievalConfig(AthenaConfigModel):
    """Root configuration for retrieval.toml."""

    provider: RetrievalProviderConfig = Field(default_factory=RetrievalProviderConfig)
    embedding: EmbeddingConfig
    scopes: ScopesConfig = Field(default_factory=ScopesConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    offload: OffloadConfig = Field(default_factory=OffloadConfig)
    index: IndexCatchupConfig = Field(default_factory=IndexCatchupConfig)
