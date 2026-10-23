import csv
import os
import re
import sys
from pathlib import Path
from typing import Any

from django.core.exceptions import FieldDoesNotExist

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIRECTORY = PROJECT_ROOT / "apps" / "data"
TABLE_FILE_PATTERN = re.compile(r"^\d+_(?P<table>.+)$")

sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.apps import apps
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Model, UniqueConstraint


def get_table_name(csv_path: Path) -> str:
    match = TABLE_FILE_PATTERN.fullmatch(csv_path.stem)
    if match is None:
        raise ValueError(
            f"CSV filename must follow 'order_tablename.csv': {csv_path.name}"
        )
    return match.group("table")


def get_model_for_table(table_name: str) -> type[Model]:
    for model in apps.get_models():
        if model._meta.db_table == table_name:
            return model
    raise LookupError(f"No Django model is mapped to table {table_name!r}.")


def get_model_field(model: type[Model], field_name: str):
    try:
        return model._meta.get_field(field_name)
    except FieldDoesNotExist as exc:
        for field in model._meta.concrete_fields:
            if field.column == field_name:
                return field
        raise ValueError(
            f"Model {model._meta.label} has no field or column {field_name!r}."
        ) from exc


def find_foreign_key(model: type[Model], table_name: str):
    target_model = get_model_for_table(table_name)
    foreign_keys = [
        field
        for field in model._meta.concrete_fields
        if field.is_relation and field.remote_field.model == target_model
    ]
    if len(foreign_keys) != 1:
        raise ValueError(
            f"Expected one foreign key from {model._meta.label} to "
            f"{table_name!r}, found {len(foreign_keys)}."
        )
    return foreign_keys[0], target_model


def parse_value(field: Any, value: str) -> Any:
    if value == "" and field.null:
        return None
    return field.to_python(value)


def resolve_foreign_key(
    model: type[Model], header: str, value: str, database: str
) -> tuple[Any, Any]:
    parts = header.split("__")
    if len(parts) != 3 or parts[0] != "fk":
        raise ValueError(f"Invalid foreign-key column name: {header!r}.")

    relation, target_model = find_foreign_key(model, parts[1])
    target_field = get_model_field(target_model, parts[2])
    if target_field.is_relation:
        raise ValueError(
            f"Foreign-key target {parts[1]}__{parts[2]} must be a scalar field."
        )

    target_value = parse_value(target_field, value)
    related_object = (
        target_model._base_manager.using(database)
        .filter(**{target_field.name: target_value})
        .first()
    )
    if related_object is None:
        raise LookupError(
            f"{model._meta.label} column {header!r} references missing "
            f"{target_model._meta.label}.{target_field.name}={target_value!r}."
        )
    return relation.attname, related_object.pk


def get_unique_field_sets(model: type[Model]) -> list[tuple[str, ...]]:
    unique_sets = [
        (field.name,)
        for field in model._meta.concrete_fields
        if field.unique
    ]
    unique_sets.extend(tuple(fields) for fields in model._meta.unique_together)
    unique_sets.extend(
        tuple(constraint.fields)
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.fields
        and constraint.condition is None
    )
    return unique_sets


def find_existing_record(model: type[Model], values: dict[str, Any], database: str):
    manager = model._base_manager.using(database)
    unique_field_sets = get_unique_field_sets(model)
    try:
        handle_field = model._meta.get_field("handle")
    except FieldDoesNotExist:
        handle_field = None

    identity_fields = (
        ("handle",)
        if handle_field is not None and handle_field.unique
        else unique_field_sets[0] if unique_field_sets else ()
    )
    identity_lookup = {}
    identity_key_present = bool(identity_fields)
    for field_name in identity_fields:
        field = get_model_field(model, field_name)
        value_name = field.attname if field.is_relation else field.name
        if value_name not in values or values[value_name] is None:
            identity_key_present = False
            break
        identity_lookup[value_name] = values[value_name]

    if identity_key_present:
        identity_record = manager.filter(**identity_lookup).first()
        if identity_record is not None:
            for field_names in unique_field_sets:
                lookup = {}
                for field_name in field_names:
                    field = get_model_field(model, field_name)
                    value_name = field.attname if field.is_relation else field.name
                    if value_name not in values or values[value_name] is None:
                        break
                    lookup[value_name] = values[value_name]
                else:
                    conflicting_record = manager.filter(**lookup).first()
                    if (
                        conflicting_record is not None
                        and conflicting_record.pk != identity_record.pk
                    ):
                        raise ValueError(
                            f"CSV row for {model._meta.label} matches multiple "
                            "existing records through unique fields."
                        )
            return identity_record

    for field_names in unique_field_sets:
        lookup = {}
        for field_name in field_names:
            field = get_model_field(model, field_name)
            value_name = field.attname if field.is_relation else field.name
            if value_name not in values or values[value_name] is None:
                break
            lookup[value_name] = values[value_name]
        else:
            existing = manager.filter(**lookup).first()
            if existing is not None:
                raise ValueError(
                    f"CSV row for {model._meta.label} conflicts with an existing "
                    f"record through unique fields {field_names!r}."
                )

    return manager.filter(**values).first() if values else None


def import_csv(csv_path: Path, database: str = DEFAULT_DB_ALIAS) -> tuple[int, int]:
    table_name = get_table_name(csv_path)
    model = get_model_for_table(table_name)
    inserted = skipped = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"CSV file has no header: {csv_path}")

        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"CSV row {row_number} in {csv_path.name} has more values "
                    "than headers."
                )

            values = {}
            for header, raw_value in row.items():
                if raw_value is None:
                    raise ValueError(
                        f"CSV row {row_number} in {csv_path.name} is missing a "
                        f"value for {header!r}."
                    )
                if header.startswith("fk__"):
                    value_name, value = resolve_foreign_key(
                        model, header, raw_value, database
                    )
                else:
                    field = get_model_field(model, header)
                    value_name = field.attname if field.is_relation else field.name
                    value = parse_value(field, raw_value)
                values[value_name] = value

            if find_existing_record(model, values, database) is not None:
                skipped += 1
                continue

            model._base_manager.using(database).create(**values)
            inserted += 1

    return inserted, skipped


def main() -> None:
    csv_files = sorted(DATA_DIRECTORY.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {DATA_DIRECTORY}.")
        return

    results = []
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        for csv_path in csv_files:
            inserted, skipped = import_csv(csv_path)
            results.append((csv_path.name, inserted, skipped))

    for file_name, inserted, skipped in results:
        print(f"{file_name}: inserted {inserted}, skipped {skipped} existing")


if __name__ == "__main__":
    main()
