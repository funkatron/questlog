"""Configuration management with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class OllamaOCRConfig(BaseModel):
    """Configuration for LLM-based OCR."""

    model: str = Field(default="moondream:latest", description="Vision model for text extraction")
    send_image: bool = Field(default=True, description="Whether to send image to vision model")


class OllamaSummarizationConfig(BaseModel):
    """Configuration for LLM-based summarization."""

    model: str = Field(default="tinydolphin:latest", description="Text model for summaries")
    send_image: bool = Field(default=False, description="Whether to send image to summarization model")


class OllamaVisionAnalysisConfig(BaseModel):
    """Configuration for vision-based holistic image analysis."""

    model: str = Field(default="", description="Vision model for scene understanding (defaults to OCR model if not set)")
    enabled: bool = Field(default=True, description="Enable vision-based analysis as primary method")


class OllamaConfig(BaseModel):
    """Ollama LLM configuration."""

    enabled: bool = Field(default=False, description="Enable Ollama integration")
    endpoint: str = Field(
        default="http://localhost:11434/api/generate",
        description="Ollama API endpoint"
    )
    ocr: OllamaOCRConfig = Field(default_factory=OllamaOCRConfig)
    summarization: OllamaSummarizationConfig = Field(default_factory=OllamaSummarizationConfig)
    vision_analysis: OllamaVisionAnalysisConfig = Field(default_factory=OllamaVisionAnalysisConfig)


class OpenAIConfig(BaseModel):
    """OpenAI API configuration."""

    enabled: bool = Field(default=False, description="Enable OpenAI integration")
    model: str = Field(default="gpt-4o-mini", description="OpenAI model to use")
    api_base: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API base URL"
    )
    api_key_env: str = Field(
        default="OPENAI_API_KEY",
        description="Environment variable name for API key"
    )
    send_image: bool = Field(default=True, description="Whether to send image to OpenAI")


class QuestlogConfig(BaseModel):
    """Main Questlog configuration."""

    base_folder: str = Field(description="Folder where screenshots are stored or watched")
    projects: List[str] = Field(default_factory=list, description="List of known project names")
    project_aliases: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Project name to alias mappings"
    )
    blocklist_apps: List[str] = Field(
        default_factory=list,
        description="Apps to skip (privacy-sensitive)"
    )
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    confidence_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for entries"
    )
    grace_gap_seconds: int = Field(
        default=120,
        ge=0,
        description="Seconds between entries to consider same session"
    )
    max_ocr_lines: int = Field(
        default=12,
        ge=1,
        le=100,
        description="Maximum OCR lines to extract"
    )
    logfile: str = Field(default="questlog.log", description="Log file path")
    log_max_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        description="Maximum log file size in bytes"
    )
    log_backups: int = Field(
        default=2,
        ge=0,
        description="Number of log backup files to keep"
    )

    @field_validator("base_folder")
    @classmethod
    def expand_user_path(cls, v: str) -> str:
        """Expand user home directory in paths."""
        return str(Path(v).expanduser())

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for backward compatibility."""
        return self.model_dump(mode="json")

    @classmethod
    def from_file(cls, config_path: Path) -> QuestlogConfig:
        """Load configuration from YAML file.

        Args:
            config_path: Path to config.yaml file.

        Returns:
            Validated QuestlogConfig instance.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config validation fails.
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid config file format: {config_path}")

        return cls(**data)


def load_config(config_path: Path | str | None = None) -> QuestlogConfig:
    """Load configuration from file.

    Args:
        config_path: Optional path to config file. Defaults to "config.yaml" in current directory.

    Returns:
        Validated QuestlogConfig instance.
    """
    if config_path is None:
        config_path = Path("config.yaml")
    elif isinstance(config_path, str):
        config_path = Path(config_path)

    return QuestlogConfig.from_file(config_path)

