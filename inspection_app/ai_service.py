"""
AI Service Wrapper around Model/inference.py.
Preserves the frozen classifier, exact preprocessing pipeline, and decision threshold.
"""

from pathlib import Path
from django.conf import settings
from Model.inference import predict as run_inference, MODEL_VERSION, CLASS_NAMES


def run_inspection_model(image_path):
    """
    Executes the frozen classifier on the specified image file.
    Does NOT infer from filenames, CSV records, or heuristics.

    Returns:
        dict: {
            "predicted_class": str ("Normal" or "Defective"),
            "confidence": float,
            "defect_probability": float,
            "model_version": str
        }
    """
    model_path = getattr(settings, 'MODEL_PATH', Path(settings.BASE_DIR) / 'Model' / 'classifier.npz')
    result = run_inference(str(image_path), model_path=str(model_path))
    return result

