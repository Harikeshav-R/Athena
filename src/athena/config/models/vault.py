"""Obsidian vault structure, indexing exclusions, and naming schema configuration models."""

from __future__ import annotations

from pydantic import Field

from athena.config.models.base import AthenaConfigModel, non_reloadable_field


class CourseSubdirsConfig(AthenaConfigModel):
    """Subdirectory layout within each course folder."""

    lectures: str = "lectures"
    slides: str = "slides"
    assignments: str = "assignments"
    readings: str = "readings"
    notes: str = "notes"


class VaultStructureConfig(AthenaConfigModel):
    """Directory tree layout for the Obsidian vault."""

    athena_dir: str = "_athena"
    memories_dir: str = "_athena/memories"
    inbox_dir: str = "_athena/inbox"
    media_dir: str = "media"
    courses_dir: str = "courses"
    projects_dir: str = "projects"
    journal_dir: str = "journal"
    people_dir: str = "people"
    references_dir: str = "references"
    course_subdirs: CourseSubdirsConfig = Field(default_factory=CourseSubdirsConfig)


class VaultIndexingConfig(AthenaConfigModel):
    """Directories excluded from chunking and embedding."""

    exclude: list[str] = Field(default_factory=lambda: ["media", "_athena/logs", "_athena/inbox"])


class VaultNamingConfig(AthenaConfigModel):
    """Templates for dated and structured document paths (D-02, D-03)."""

    lecture: str = "{year}/{month:02d}/{date}-lecture-{sequence:02d}"
    slide_deck: str = "{year}/{month:02d}/{date}-{title_slug}"
    assignment: str = "{assignment_slug}"
    journal: str = "{year}/{month:02d}/{date}"
    slug_max_length: int = 60


class VaultConfig(AthenaConfigModel):
    """Root configuration for vault.toml."""

    root: str = non_reloadable_field(default="/vault")
    structure: VaultStructureConfig = Field(default_factory=VaultStructureConfig)
    indexing: VaultIndexingConfig = Field(default_factory=VaultIndexingConfig)
    naming: VaultNamingConfig = Field(default_factory=VaultNamingConfig)
