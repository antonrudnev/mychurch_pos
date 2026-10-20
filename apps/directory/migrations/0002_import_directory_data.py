import csv
from decimal import Decimal
from pathlib import Path

from django.db import migrations


def parse_boolean(value):
    normalized = value.lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"Invalid boolean value in directory CSV: {value!r}")


def import_directory_data(apps, schema_editor):
    ItemType = apps.get_model("directory", "ItemType")
    Item = apps.get_model("directory", "Item")
    database = schema_editor.connection.alias
    data_directory = Path(__file__).resolve().parent.parent / "data"

    with (data_directory / "item_type.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        item_type_rows = list(csv.DictReader(csv_file))

    existing_type_handles = set(
        ItemType.objects.using(database).values_list("handle", flat=True)
    )
    ItemType.objects.using(database).bulk_create([
        ItemType(
            name=row["name"],
            handle=row["handle"],
            is_product_group=parse_boolean(row["is_product_group"]),
            is_open_list=parse_boolean(row["is_open_list"]),
            order_number=int(row["order_number"]),
        )
        for row in item_type_rows
        if row["handle"] not in existing_type_handles
    ])

    item_types = {
        item_type.handle: item_type
        for item_type in ItemType.objects.using(database).all()
    }

    with (data_directory / "item.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        item_rows = list(csv.DictReader(csv_file))

    existing_item_handles = set(
        Item.objects.using(database).values_list("handle", flat=True)
    )
    items = []
    for row in item_rows:
        if row["handle"] in existing_item_handles:
            continue

        item_type_handle = row["item_type"]
        if item_type_handle not in item_types:
            raise ValueError(
                f"Item {row['handle']!r} references unknown item type "
                f"{item_type_handle!r}."
            )

        items.append(Item(
            item_type_id=item_types[item_type_handle].pk,
            name=row["name"],
            handle=row["handle"],
            price=None if row["price"] == "None" else Decimal(row["price"]),
            is_active=parse_boolean(row["is_active"]),
            order_number=int(row["order_number"]),
        ))

    Item.objects.using(database).bulk_create(items)


class Migration(migrations.Migration):
    dependencies = [
        ("directory", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(import_directory_data, migrations.RunPython.noop),
    ]
