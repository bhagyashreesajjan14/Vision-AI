"""
File and image content validators for AI Visual Quality Inspection.
Enforces:
1. Decoded JPEG or PNG content only (rejects disguised files and corrupt data).
2. Maximum file size of 5 MiB (5,242,880 bytes).
3. Image dimensions between 64 and 4096 pixels inclusive.
"""

from io import BytesIO
from pathlib import Path
import os
from PIL import Image, UnidentifiedImageError

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MiB
MIN_DIMENSION_PX = 64
MAX_DIMENSION_PX = 4096
ALLOWED_FORMATS = ('JPEG', 'PNG')


def validate_image_file(file_input):
    """
    Validates an uploaded image file, byte stream, or filesystem path.

    Returns:
        tuple (is_valid: bool, error_message: str | None, metadata: dict | None)
        Metadata dictionary on success:
            {'format': str, 'width': int, 'height': int, 'size': int}
    """
    # 1. Determine file size and seekable stream
    if hasattr(file_input, 'size'):
        file_size = file_input.size
    elif isinstance(file_input, (str, Path)):
        if not os.path.exists(file_input):
            return False, f"File does not exist: {file_input}", None
        file_size = os.path.getsize(file_input)
    elif hasattr(file_input, 'seek') and hasattr(file_input, 'tell'):
        current_pos = file_input.tell()
        file_input.seek(0, os.SEEK_END)
        file_size = file_input.tell()
        file_input.seek(current_pos)
    else:
        return False, "Invalid file input type provided.", None

    if file_size <= 0:
        return False, "File is empty (0 bytes).", None

    if file_size > MAX_FILE_SIZE_BYTES:
        mb = file_size / (1024 * 1024)
        return False, f"File size exceeds 5 MiB limit: {mb:.2f} MiB ({file_size} bytes).", None

    # 2. Verify decoded image integrity and actual format
    # Note: verify() checks header integrity but closes/invalidates the image object in Pillow,
    # so we verify first, then re-open to inspect dimensions safely.
    try:
        if hasattr(file_input, 'seek'):
            file_input.seek(0)
            img = Image.open(file_input)
        else:
            img = Image.open(file_input)

        raw_format = (img.format or '').upper()
        # Treat 'JPG' as 'JPEG'
        if raw_format == 'JPG':
            raw_format = 'JPEG'

        if raw_format not in ALLOWED_FORMATS:
            return False, f"Unsupported image format '{raw_format}'. Only decoded JPEG and PNG are allowed.", None

        img.verify()
    except UnidentifiedImageError:
        return False, "Corrupted or unrecognizable image content. File is not a valid decoded JPEG or PNG image.", None
    except Exception as exc:
        return False, f"Image verification failed: {str(exc)}", None

    # 3. Re-open to read width and height and ensure full decodability
    try:
        if hasattr(file_input, 'seek'):
            file_input.seek(0)
            with Image.open(file_input) as img_full:
                width, height = img_full.size
                # Force loading pixel data to catch truncated streams
                img_full.load()
        else:
            with Image.open(file_input) as img_full:
                width, height = img_full.size
                img_full.load()
    except Exception as exc:
        return False, f"Image data decoding error: {str(exc)}", None

    # 4. Dimension constraints (64px to 4096px inclusive)
    if width < MIN_DIMENSION_PX or width > MAX_DIMENSION_PX:
        return False, f"Image width {width}px is outside the allowed range [{MIN_DIMENSION_PX}, {MAX_DIMENSION_PX}] pixels.", None

    if height < MIN_DIMENSION_PX or height > MAX_DIMENSION_PX:
        return False, f"Image height {height}px is outside the allowed range [{MIN_DIMENSION_PX}, {MAX_DIMENSION_PX}] pixels.", None

    # Reset stream pointer for downstream callers
    if hasattr(file_input, 'seek'):
        file_input.seek(0)

    metadata = {
        'format': raw_format,
        'width': width,
        'height': height,
        'size': file_size,
    }
    return True, None, metadata


def validate_batch_file_count(files_list):
    """
    Validates batch file count is between 1 and 10 inclusive.
    """
    count = len(files_list)
    if count == 0:
        return False, "A batch must contain at least 1 image file."
    if count > 10:
        return False, f"Batch size cannot exceed 10 files. Received {count} files."
    return True, None

