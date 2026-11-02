import csv
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from inspection_app.models import Product


class Command(BaseCommand):
    help = "Seeds products from product_details.csv into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=str(settings.BASE_DIR / 'product_details.csv'),
            help='Path to product CSV file'
        )

    def handle(self, *args, **options):
        csv_path = options['file']
        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f"CSV file not found at: {csv_path}"))
            return

        seeded_count = 0
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_id = row.get('product_id', '').strip()
                p_name = row.get('product_name', '').strip()
                p_desc = row.get('description', '').strip()
                if p_id:
                    prod, created = Product.objects.update_or_create(
                        product_id=p_id,
                        defaults={
                            'product_name': p_name,
                            'description': p_desc,
                            'is_active': True,
                        }
                    )
                    status_text = "Created" if created else "Updated"
                    self.stdout.write(self.style.SUCCESS(f"{status_text} product: {prod.product_id} - {prod.product_name}"))
                    seeded_count += 1

        self.stdout.write(self.style.SUCCESS(f"Total products processed: {seeded_count}"))

