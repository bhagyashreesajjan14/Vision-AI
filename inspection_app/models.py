import uuid
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """
    Extends the built-in Django User model with application-specific roles:
    - ADMINISTRATOR: Product management and system administration
    - ENGINEER: Image submission (single & batch) and viewing own inspection history
    - SUPERVISOR: Viewing all inspections and confirming/correcting completed inspections
    """
    ROLE_ADMINISTRATOR = 'ADMINISTRATOR'
    ROLE_ENGINEER = 'ENGINEER'
    ROLE_SUPERVISOR = 'SUPERVISOR'

    ROLE_CHOICES = [
        (ROLE_ADMINISTRATOR, 'Administrator'),
        (ROLE_ENGINEER, 'Engineer'),
        (ROLE_SUPERVISOR, 'Supervisor'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ENGINEER)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_administrator(self):
        return self.role == self.ROLE_ADMINISTRATOR or self.user.is_superuser

    @property
    def is_engineer(self):
        return self.role == self.ROLE_ENGINEER

    @property
    def is_supervisor(self):
        return self.role == self.ROLE_SUPERVISOR


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        role = UserProfile.ROLE_ADMINISTRATOR if instance.is_superuser else UserProfile.ROLE_ENGINEER
        UserProfile.objects.get_or_create(user=instance, defaults={'role': role})
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()


class Product(models.Model):
    """
    Supported products registered by Administrators (e.g. P-PLATE01).
    """
    product_id = models.CharField(max_length=64, primary_key=True)
    product_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product_id']

    def __str__(self):
        return f"{self.product_id} - {self.product_name}"


class InspectionBatch(models.Model):
    """
    A batch inspection container representing an upload of 1 to 10 images
    processed in the background via Celery.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batches')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='batches')
    total_items = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch {self.id} ({self.product.product_id if self.product else 'No Product'}) by {self.user.username}"

    @property
    def completed_count(self):
        return self.items.filter(status='COMPLETED').count()

    @property
    def failed_count(self):
        return self.items.filter(status='FAILED').count()

    @property
    def processing_count(self):
        return self.items.filter(status='PROCESSING').count()

    @property
    def queued_count(self):
        return self.items.filter(status='QUEUED').count()

    @property
    def is_finished(self):
        return self.items.filter(status__in=['QUEUED', 'PROCESSING']).count() == 0

    @property
    def batch_tracking_id(self):
        return f"BATCH-{str(self.id)[:8].upper()}"

    @property
    def normal_count(self):
        return self.items.filter(status='COMPLETED', predicted_class='Normal').count()

    @property
    def defective_count(self):
        return self.items.filter(status='COMPLETED', predicted_class='Defective').count()

    @property
    def defect_rate(self):
        comp = self.completed_count
        if comp > 0:
            return round((self.defective_count / comp) * 100, 1)
        return 0.0

    @property
    def pass_rate(self):
        comp = self.completed_count
        if comp > 0:
            return round((self.normal_count / comp) * 100, 1)
        return 0.0

    @property
    def average_confidence(self):
        from django.db.models import Avg
        avg_val = self.items.filter(status='COMPLETED', confidence__isnull=False).aggregate(Avg('confidence'))['confidence__avg']
        return round(avg_val, 4) if avg_val is not None else None

    @property
    def processing_duration(self):
        latest = self.items.filter(completed_at__isnull=False).order_by('-completed_at').first()
        if latest and latest.completed_at and self.created_at:
            delta = (latest.completed_at - self.created_at).total_seconds()
            return max(0.0, round(delta, 2))
        return None


class InspectionItem(models.Model):
    """
    An individual inspection record.
    The original AI prediction is IMMUTABLE once written.
    """
    STATUS_QUEUED = 'QUEUED'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(InspectionBatch, on_delete=models.CASCADE, null=True, blank=True, related_name='items')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='inspections')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='inspections')
    image = models.ImageField(upload_to='inspections/%Y/%m/%d/', null=True, blank=True)
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    image_width = models.IntegerField(null=True, blank=True)
    image_height = models.IntegerField(null=True, blank=True)
    image_format = models.CharField(max_length=16, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    failure_reason = models.TextField(blank=True, default='')

    # Immutable original AI model predictions
    predicted_class = models.CharField(max_length=32, blank=True, null=True)  # 'Normal' or 'Defective'
    confidence = models.FloatField(blank=True, null=True)                      # 0.0 to 1.0
    defect_probability = models.FloatField(blank=True, null=True)              # 0.0 to 1.0
    model_version = models.CharField(max_length=64, blank=True, null=True)     # e.g. 'BIT-PLATE-CV-1.0'

    # Defect Localization / Highlighting
    # Note: Model BIT-PLATE-CV-1.0 only classifies Normal/Defective and does NOT output defect coordinates.
    # When Defective, localization defaults to UNAVAILABLE until manually annotated by a supervisor.
    LOCALIZATION_UNAVAILABLE = 'UNAVAILABLE'
    LOCALIZATION_MANUAL = 'MANUALLY_ANNOTATED'
    LOCALIZATION_MODEL = 'MODEL_DETECTED'

    LOCALIZATION_CHOICES = [
        (LOCALIZATION_UNAVAILABLE, 'Defect location unavailable from model'),
        (LOCALIZATION_MANUAL, 'Manually annotated by supervisor'),
        (LOCALIZATION_MODEL, 'Model detected localization'),
    ]

    defect_localization_status = models.CharField(
        max_length=64,
        choices=LOCALIZATION_CHOICES,
        default=LOCALIZATION_UNAVAILABLE
    )
    annotated_image = models.ImageField(upload_to='annotated/%Y/%m/%d/', null=True, blank=True)
    defect_annotations = models.JSONField(default=list, blank=True)  # List of bounding box dicts [x1, y1, x2, y2]

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Inspection {self.id} [{self.status}] - {self.original_filename}"

    @property
    def has_review(self):
        return hasattr(self, 'review') and self.review is not None

    @property
    def tracking_id(self):
        return f"QC-{str(self.id)[:8].upper()}"

    @property
    def image_sha256(self):
        if self.image:
            try:
                import hashlib
                import os
                if hasattr(self.image, 'path') and os.path.exists(self.image.path):
                    h = hashlib.sha256()
                    with open(self.image.path, 'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b''):
                            h.update(chunk)
                    return h.hexdigest()
            except Exception:
                pass
        return None

    @property
    def processing_duration(self):
        if self.completed_at and self.created_at:
            delta = (self.completed_at - self.created_at).total_seconds()
            return max(0.0, round(delta, 3))
        return None


class SupervisorReview(models.Model):
    """
    Supervisor confirmation or correction of an inspection prediction.
    Stored strictly separately from the original AI prediction.
    """
    CLASS_NORMAL = 'Normal'
    CLASS_DEFECTIVE = 'Defective'

    CLASS_CHOICES = [
        (CLASS_NORMAL, 'Normal'),
        (CLASS_DEFECTIVE, 'Defective'),
    ]

    ACTION_CONFIRMED = 'CONFIRMED'
    ACTION_CORRECTED = 'CORRECTED'

    ACTION_CHOICES = [
        (ACTION_CONFIRMED, 'Confirmed'),
        (ACTION_CORRECTED, 'Corrected'),
    ]

    inspection = models.OneToOneField(InspectionItem, on_delete=models.CASCADE, related_name='review')
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='supervisor_reviews')
    reviewed_class = models.CharField(max_length=32, choices=CLASS_CHOICES)
    review_action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True, default='')
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reviewed_at']

    def __str__(self):
        return f"Review by {self.reviewer.username}: {self.review_action} -> {self.reviewed_class}"
