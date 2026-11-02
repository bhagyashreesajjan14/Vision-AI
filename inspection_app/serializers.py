"""
Django REST Framework serializers for API endpoints.
"""

from rest_framework import serializers
from .models import Product, InspectionBatch, InspectionItem, SupervisorReview


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['product_id', 'product_name', 'description', 'is_active', 'created_at']


class SupervisorReviewSerializer(serializers.ModelSerializer):
    reviewer_username = serializers.CharField(source='reviewer.username', read_only=True)

    class Meta:
        model = SupervisorReview
        fields = [
            'id',
            'reviewer',
            'reviewer_username',
            'reviewed_class',
            'review_action',
            'comment',
            'reviewed_at',
        ]
        read_only_fields = ['reviewer', 'review_action', 'reviewed_at']


class InspectionItemSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    product_name = serializers.CharField(source='product.product_name', read_only=True)
    review = SupervisorReviewSerializer(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = InspectionItem
        fields = [
            'id',
            'batch',
            'user',
            'user_username',
            'product',
            'product_name',
            'image_url',
            'original_filename',
            'file_size_bytes',
            'image_width',
            'image_height',
            'image_format',
            'status',
            'failure_reason',
            'predicted_class',
            'confidence',
            'defect_probability',
            'model_version',
            'created_at',
            'completed_at',
            'review',
        ]
        read_only_fields = [
            'id', 'user', 'status', 'failure_reason', 'predicted_class',
            'confidence', 'defect_probability', 'model_version', 'created_at',
            'completed_at', 'review',
        ]

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        return None


class InspectionBatchSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    product_name = serializers.CharField(source='product.product_name', read_only=True)
    items = InspectionItemSerializer(many=True, read_only=True)
    completed_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    processing_count = serializers.IntegerField(read_only=True)
    queued_count = serializers.IntegerField(read_only=True)
    is_finished = serializers.BooleanField(read_only=True)

    class Meta:
        model = InspectionBatch
        fields = [
            'id',
            'user_username',
            'product',
            'product_name',
            'total_items',
            'completed_count',
            'failed_count',
            'processing_count',
            'queued_count',
            'is_finished',
            'created_at',
            'items',
        ]


class CreateReviewSerializer(serializers.Serializer):
    reviewed_class = serializers.ChoiceField(choices=['Normal', 'Defective'])
    comment = serializers.CharField(required=False, allow_blank=True, default='')

