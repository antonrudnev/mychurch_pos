import csv
from pathlib import Path

from django.db import migrations


def import_report_types(apps, schema_editor):
    ReportType = apps.get_model("reports", "ReportType")
    database = schema_editor.connection.alias
    csv_path = Path(__file__).resolve().parent.parent / "data" / "report_type.csv"

    with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            ReportType.objects.using(database).get_or_create(
                handle=row["handle"],
                defaults={"name": row["name"]},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(import_report_types, migrations.RunPython.noop),
    ]
