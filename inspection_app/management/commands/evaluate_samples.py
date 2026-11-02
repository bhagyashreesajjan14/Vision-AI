import csv
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from inspection_app.ai_service import run_inspection_model


class Command(BaseCommand):
    help = "Evaluates the frozen AI classifier on all 60 labeled samples and generates Confusion Matrix & Defect Recall"

    def handle(self, *args, **options):
        samples_dir = Path(settings.BASE_DIR) / 'Samples'
        labels_path = samples_dir / 'labels.csv'

        if not labels_path.exists():
            self.stderr.write(self.style.ERROR(f"Labels file not found at: {labels_path}"))
            return

        cm = {'Normal': {'Normal': 0, 'Defective': 0}, 'Defective': {'Normal': 0, 'Defective': 0}}
        total = 0
        failed = 0

        self.stdout.write(self.style.NOTICE("Running inference across all 60 sample images..."))

        with open(labels_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                img_path = samples_dir / row['relative_path']
                actual = row['label']

                try:
                    pred = run_inspection_model(img_path)
                    pred_class = pred['predicted_class']
                    cm[actual][pred_class] += 1
                except Exception as exc:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"Error predicting {row['image_id']}: {exc}"))

        tp = cm['Defective']['Defective']
        fn = cm['Defective']['Normal']
        fp = cm['Normal']['Defective']
        tn = cm['Normal']['Normal']

        defect_recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0
        accuracy = ((tp + tn) / (tp + tn + fp + fn)) if (tp + tn + fp + fn) > 0 else 0

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("EVALUATION RESULTS (All 60 Samples)"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total Evaluated: {total}")
        self.stdout.write(f"Failed Predictions: {failed}")
        self.stdout.write("\nCONFUSION MATRIX (Rows: Actual, Columns: Predicted):")
        self.stdout.write(f"  Actual Normal    | Predicted Normal: {tn:<3} | Predicted Defective: {fp:<3}")
        self.stdout.write(f"  Actual Defective | Predicted Normal: {fn:<3} | Predicted Defective: {tp:<3}")
        self.stdout.write("-" * 60)
        self.stdout.write(f"True Positives (TP):   {tp}")
        self.stdout.write(f"False Negatives (FN):  {fn}")
        self.stdout.write(f"False Positives (FP):  {fp}")
        self.stdout.write(f"True Negatives (TN):   {tn}")
        self.stdout.write(self.style.SUCCESS(f"Defect Recall [TP / (TP + FN)]: {defect_recall:.4f} ({defect_recall * 100:.2f}%)"))
        self.stdout.write(self.style.SUCCESS(f"Overall Accuracy:               {accuracy:.4f} ({accuracy * 100:.2f}%)"))
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.WARNING(
            "\nSYNTHETIC DATASET LIMITATIONS NOTE:\n"
            "This model operates on standardized synthetic illustrations with fixed centering and framing.\n"
            "Scores are uncalibrated and procedural defect features do not reflect real factory variability,\n"
            "lighting shifts, camera angles, or true structural defect distributions.\n"
        ))

