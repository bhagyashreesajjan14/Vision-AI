"""
Celery asynchronous tasks for Visual Quality Inspection.
Handles background batch processing, per-item status updates, and fault tolerance.
"""

import logging
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import InspectionBatch, InspectionItem
from .validators import validate_image_file
from .ai_service import run_inspection_model

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def process_inspection_batch(self, batch_id):
    """
    Asynchronously processes all items in an inspection batch.
    Individual item failures (corrupt/invalid files) do NOT halt the remaining items.
    """
    try:
        batch = InspectionBatch.objects.get(id=batch_id)
    except InspectionBatch.DoesNotExist:
        logger.error(f"InspectionBatch {batch_id} not found.")
        return False

    items = batch.items.all().order_by('created_at')

    for item in items:
        # If already completed or failed, skip
        if item.status in [InspectionItem.STATUS_COMPLETED, InspectionItem.STATUS_FAILED]:
            continue

        item.status = InspectionItem.STATUS_PROCESSING
        item.save(update_fields=['status'])

        try:
            if not item.image:
                item.status = InspectionItem.STATUS_FAILED
                item.failure_reason = "No image file associated with inspection record."
                item.save(update_fields=['status', 'failure_reason'])
                continue

            file_path = item.image.path

            # Validate image content, size, and dimensions before calling model
            is_valid, error_msg, metadata = validate_image_file(file_path)

            if not is_valid:
                # Persist as failed attempt without calling the model
                item.status = InspectionItem.STATUS_FAILED
                item.failure_reason = error_msg or "Image failed validation checks."
                item.save(update_fields=['status', 'failure_reason'])
                logger.warning(f"Batch item {item.id} rejected: {item.failure_reason}")
                continue

            # Update validated file metadata
            item.file_size_bytes = metadata.get('size')
            item.image_width = metadata.get('width')
            item.image_height = metadata.get('height')
            item.image_format = metadata.get('format')

            # Run frozen AI model inference
            prediction = run_inspection_model(file_path)

            item.predicted_class = prediction['predicted_class']
            item.confidence = prediction['confidence']
            item.defect_probability = prediction['defect_probability']
            item.model_version = prediction['model_version']
            item.status = InspectionItem.STATUS_COMPLETED
            item.completed_at = timezone.now()
            item.failure_reason = ""

            item.save()
            logger.info(f"Batch item {item.id} completed: {item.predicted_class} ({item.confidence:.4f})")

        except Exception as exc:
            logger.error(f"Error processing inspection item {item.id}: {exc}", exc_info=True)
            item.status = InspectionItem.STATUS_FAILED
            item.failure_reason = f"Processing error: {str(exc)}"
            item.save(update_fields=['status', 'failure_reason'])

    return True


def dispatch_batch_processing(batch):
    """
    Dispatches batch processing task.
    Uses Celery worker via Redis if configured/available.
    Gracefully falls back to direct execution if Redis broker is offline or eager mode is enabled.
    """
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        process_inspection_batch(str(batch.id))
        return "synchronous"

    try:
        process_inspection_batch.delay(str(batch.id))
        return "queued_celery"
    except Exception as exc:
        logger.warning(f"Celery dispatch failed ({exc}), falling back to synchronous execution.")
        process_inspection_batch(str(batch.id))
        return "synchronous_fallback"

