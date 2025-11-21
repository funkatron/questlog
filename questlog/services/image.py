"""Image processing service."""

import datetime as dt
import logging
from pathlib import Path
from typing import Optional

import ql.processing as qlp
import ql.system as qls
from questlog.config import QuestlogConfig

logger = logging.getLogger("questlog")


class ImageService:
    """Service for image processing operations."""

    def __init__(
        self,
        config: QuestlogConfig,
        frontapp_bin: Path = Path("bin/frontapp"),
        ocr_bin: Path = Path("bin/ocrshot"),
    ):
        """Initialize image service.

        Args:
            config: Questlog configuration.
            frontapp_bin: Path to Swift frontapp binary.
            ocr_bin: Path to Swift OCR binary.
        """
        self.config = config
        self.frontapp_bin = frontapp_bin
        self.ocr_bin = ocr_bin

    def front_app_info(self) -> dict[str, str]:
        """Get information about the frontmost application.

        Returns:
            Dictionary with app name, bundle_id, and window_title.
        """
        return qls.front_app_info(self.frontapp_bin)

    def ocr_lines(self, path: Path, max_lines: int) -> list[str]:
        """Extract text lines from an image using OCR.

        Args:
            path: Path to the image file.
            max_lines: Maximum number of lines to return.

        Returns:
            List of OCR-extracted text lines.
        """
        lines = qls.ocr_lines(self.ocr_bin, path, max_lines)
        if not lines and not self.ocr_bin.exists():
            logger.warning("ocr binary missing at %s", self.ocr_bin)
        return lines

    def ensure_today_dir(self, base_folder: Path) -> Path:
        """Ensure today's date directory exists in base folder.

        Args:
            base_folder: Base folder path.

        Returns:
            Path to today's directory.
        """
        today_dir = base_folder / dt.date.today().strftime("%Y-%m-%d")
        today_dir.mkdir(parents=True, exist_ok=True)
        return today_dir

    def process_image(
        self, conn, file_path: Path
    ) -> Optional[int]:
        """Process an image and create database entry.

        Args:
            conn: Database connection.
            file_path: Path to image file.

        Returns:
            Entry ID if successful, None otherwise.
        """
        return qlp.process_image(
            conn, self.config.to_dict(), file_path, self.frontapp_bin, self.ocr_bin
        )

    def iter_images(self, base_folder: Path):
        """Iterate over image files in base folder.

        Args:
            base_folder: Base folder path.

        Yields:
            Path objects for image files.
        """
        return qlp.iter_images(base_folder)

