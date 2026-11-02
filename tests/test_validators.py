import os
from io import BytesIO
from pathlib import Path
from PIL import Image
from django.test import TestCase
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from inspection_app.validators import (
    validate_image_file,
    validate_batch_file_count,
    MAX_FILE_SIZE_BYTES,
    MIN_DIMENSION_PX,
    MAX_DIMENSION_PX,
)


class ImageValidatorTests(TestCase):
    """
    Test suite for pre-inference image validation:
    - Decoded JPEG/PNG content
    - File size limits (<= 5 MiB)
    - Dimension boundaries (64 to 4096 pixels)
    - Rejection of invalid inputs from the Validation/ pack
    """

    def setUp(self):
        self.validation_dir = Path(settings.BASE_DIR) / 'Validation'
        self.samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'

    def test_corrupt_png_rejected(self):
        """Validation/corrupt_image.png must be rejected."""
        corrupt_path = self.validation_dir / 'corrupt_image.png'
        is_valid, error, meta = validate_image_file(corrupt_path)
        self.assertFalse(is_valid)
        self.assertIn("Corrupted or unrecognizable", error)
        self.assertIsNone(meta)

    def test_not_an_image_txt_with_jpg_extension_rejected(self):
        """Validation/not_an_image.jpg must be rejected."""
        fake_path = self.validation_dir / 'not_an_image.jpg'
        is_valid, error, meta = validate_image_file(fake_path)
        self.assertFalse(is_valid)
        self.assertIn("Corrupted or unrecognizable", error)
        self.assertIsNone(meta)

    def test_too_small_image_rejected(self):
        """Validation/too_small.png (32x32) must be rejected because dimension < 64."""
        small_path = self.validation_dir / 'too_small.png'
        is_valid, error, meta = validate_image_file(small_path)
        self.assertFalse(is_valid)
        self.assertIn("outside the allowed range", error)
        self.assertIn(str(MIN_DIMENSION_PX), error)
        self.assertIsNone(meta)

    def test_valid_sample_image_accepted(self):
        """Samples/images/inspection_001.png (256x256) must be accepted."""
        valid_path = self.samples_dir / 'inspection_001.png'
        is_valid, error, meta = validate_image_file(valid_path)
        self.assertTrue(is_valid)
        self.assertIsNone(error)
        self.assertIsNotNone(meta)
        self.assertEqual(meta['format'], 'PNG')
        self.assertEqual(meta['width'], 256)
        self.assertEqual(meta['height'], 256)

    def test_oversized_dimension_rejected(self):
        """Image with dimension > 4096 px must be rejected."""
        # Create an in-memory 4097x64 image
        bio = BytesIO()
        img = Image.new('RGB', (4097, 64), color='white')
        img.save(bio, format='PNG')
        bio.seek(0)
        uploaded = SimpleUploadedFile("too_wide.png", bio.getvalue(), content_type="image/png")

        is_valid, error, meta = validate_image_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("outside the allowed range", error)

    def test_file_size_exceeding_5mb_rejected(self):
        """File larger than 5 MiB must be rejected."""
        oversized_bytes = b'0' * (5 * 1024 * 1024 + 100)
        uploaded = SimpleUploadedFile("oversized.png", oversized_bytes, content_type="image/png")

        is_valid, error, meta = validate_image_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("exceeds 5 MiB limit", error)

    def test_unsupported_format_rejected(self):
        """GIF or BMP format must be rejected even if valid image data."""
        bio = BytesIO()
        img = Image.new('RGB', (100, 100), color='white')
        img.save(bio, format='GIF')
        bio.seek(0)
        uploaded = SimpleUploadedFile("image.gif", bio.getvalue(), content_type="image/gif")

        is_valid, error, meta = validate_image_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("Unsupported image format", error)

    def test_batch_file_count_validation(self):
        """Batch count must be between 1 and 10."""
        self.assertFalse(validate_batch_file_count([])[0])
        self.assertTrue(validate_batch_file_count([1])[0])
        self.assertTrue(validate_batch_file_count([1] * 10)[0])
        self.assertFalse(validate_batch_file_count([1] * 11)[0])

