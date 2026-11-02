"""
Django Admin registration for Visual Quality Inspection models.
"""

from django.contrib import admin
from .models import UserProfile, Product, InspectionBatch, InspectionItem, SupervisorReview


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role']
    list_filter = ['role']
    search_fields = ['user__username', 'user__email']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['product_id', 'product_name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['product_id', 'product_name']


class InspectionItemInline(admin.TabularInline):
    model = InspectionItem
    extra = 0
    readonly_fields = ['id', 'status', 'predicted_class', 'confidence', 'defect_probability', 'model_version', 'created_at']
    fields = ['original_filename', 'status', 'predicted_class', 'confidence', 'failure_reason']


@admin.register(InspectionBatch)
class InspectionBatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'product', 'user', 'total_items', 'created_at']
    list_filter = ['product', 'created_at']
    search_fields = ['id', 'user__username', 'product__product_id']
    inlines = [InspectionItemInline]


class SupervisorReviewInline(admin.StackedInline):
    model = SupervisorReview
    extra = 0
    readonly_fields = ['reviewed_at']


@admin.register(InspectionItem)
class InspectionItemAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'product', 'user', 'original_filename', 'status',
        'predicted_class', 'confidence', 'created_at', 'has_review'
    ]
    list_filter = ['status', 'predicted_class', 'product', 'created_at']
    search_fields = ['id', 'original_filename', 'user__username']
    readonly_fields = [
        'id', 'created_at', 'completed_at', 'predicted_class',
        'confidence', 'defect_probability', 'model_version'
    ]
    inlines = [SupervisorReviewInline]


@admin.register(SupervisorReview)
class SupervisorReviewAdmin(admin.ModelAdmin):
    list_display = ['inspection', 'reviewer', 'reviewed_class', 'review_action', 'reviewed_at']
    list_filter = ['review_action', 'reviewed_class', 'reviewed_at']
    search_fields = ['reviewer__username', 'inspection__id', 'comment']
