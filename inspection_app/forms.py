"""
Forms for the AI Visual Quality Inspection web application.
"""

from django import forms
from .models import Product, InspectionItem, SupervisorReview
from .validators import MAX_FILE_SIZE_BYTES


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class SingleInspectionForm(forms.Form):
    """
    Form for uploading a single image inspection.
    """
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        empty_label="-- Select Target Product --",
        widget=forms.Select(attrs={'class': 'form-select form-select-lg', 'required': 'required'})
    )
    image = forms.FileField(
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control form-control-lg',
            'accept': 'image/png,image/jpeg',
            'id': 'singleImageInput',
            'required': 'required'
        }),
        help_text="Accepts JPEG or PNG up to 5 MiB with dimensions 64x64 to 4096x4096px."
    )


class BatchInspectionForm(forms.Form):
    """
    Form for uploading a batch of 1 to 10 images.
    """
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        empty_label="-- Select Target Product --",
        widget=forms.Select(attrs={'class': 'form-select form-select-lg', 'required': 'required'})
    )
    images = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'class': 'form-control form-control-lg',
            'accept': 'image/png,image/jpeg',
            'id': 'batchImagesInput',
            'multiple': 'multiple',
            'required': 'required'
        }),
        help_text="Select 1 to 10 JPEG or PNG images (up to 5 MiB each)."
    )

    def clean_images(self):
        files = self.files.getlist('images')
        if not files:
            raise forms.ValidationError("Please select at least 1 image file.")
        if len(files) > 10:
            raise forms.ValidationError(f"Batch cannot exceed 10 files. You selected {len(files)} files.")
        return files


class SupervisorReviewForm(forms.ModelForm):
    """
    Form for Supervisors to confirm or correct an inspection.
    """
    class Meta:
        model = SupervisorReview
        fields = ['reviewed_class', 'comment']
        widgets = {
            'reviewed_class': forms.Select(attrs={'class': 'form-select', 'required': 'required'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional supervisor note or rationale for confirmation/correction...'
            }),
        }


class ProductForm(forms.ModelForm):
    """
    Form for Administrators to add or edit products.
    """
    class Meta:
        model = Product
        fields = ['product_id', 'product_name', 'description', 'is_active']
        widgets = {
            'product_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. P-PLATE01'}),
            'product_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Demonstration metal plate'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Product description...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

