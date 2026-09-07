"""Audio ASR, PDF conversion, Canvas download, and ingestion limits configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from athena.config.models.base import AthenaConfigModel


class AudioIngestionConfig(AthenaConfigModel):
    """ASR transcription, diarization, and lecture structure settings."""

    base_url: str = "http://host.docker.internal:8081"
    model: str
    language: str = "en"
    diarize: bool = True
    word_timestamps: bool = True
    vad: bool = True
    timeout_s: float = 5400.0
    section_gap_s: float = 6.0
    section_titles: Literal["heuristic", "model", "none"] = "heuristic"
    speaker_map_source: str = "course_file"


class PdfIngestionConfig(AthenaConfigModel):
    """PDF slide rasterization and vision model conversion settings."""

    dpi: int = 150
    max_pages: int = 300
    page_concurrency: int = 2
    model_role: str = "vision"
    retry_per_page: int = 3
    checkpoint_every: int = 1


class CanvasIngestionConfig(AthenaConfigModel):
    """Canvas file download filters and size limits."""

    max_file_size_mb: int = 50
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "audio/mp4",
            "audio/mpeg",
            "audio/x-m4a",
            "text/plain",
            "text/markdown",
        ]
    )


class WatchersConfig(AthenaConfigModel):
    """Filesystem watcher debounce and scratch storage settings."""

    debounce_ms: int = 1000
    scratch_dir: str = "/tmp/athena-ingest"  # noqa: S108


class IngestionLimitsConfig(AthenaConfigModel):
    """Global upload and conversion limits."""

    max_upload_size_mb: int = 500


class IngestionConfig(AthenaConfigModel):
    """Root configuration for ingestion.toml."""

    audio: AudioIngestionConfig
    pdf: PdfIngestionConfig = Field(default_factory=PdfIngestionConfig)
    canvas: CanvasIngestionConfig = Field(default_factory=CanvasIngestionConfig)
    watchers: WatchersConfig = Field(default_factory=WatchersConfig)
    limits: IngestionLimitsConfig = Field(default_factory=IngestionLimitsConfig)
