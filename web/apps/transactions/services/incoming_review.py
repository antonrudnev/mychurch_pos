from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import IncomingTransaction, Transaction


def _create_transaction(incoming_transaction, user):
    if incoming_transaction.is_deleted or incoming_transaction.transaction_id:
        raise ValidationError('Эта входящая строка уже обработана или удалена.')

    created_at = (
        timezone.make_aware(
            datetime.combine(incoming_transaction.report_date, time(hour=12))
        )
        if incoming_transaction.report_date
        else timezone.now()
    )
    transaction_record = Transaction(
        item=incoming_transaction.item,
        price=incoming_transaction.price,
        quantity=incoming_transaction.quantity,
        cashier=user,
        created_at=created_at,
    )

    transaction_record.cashier = user
    transaction_record.is_verified = user.has_perm('transactions.verify_transaction')
    transaction_record.verified_by = (
        user if transaction_record.is_verified else None
    )
    transaction_record.save()

    incoming_transaction.transaction = transaction_record
    incoming_transaction.processed_by = user
    incoming_transaction.save(update_fields=('transaction', 'processed_by'))
    return transaction_record


@transaction.atomic
def create_transaction_for_incoming(incoming_transaction, user):
    locked_incoming = (
        IncomingTransaction.objects.select_for_update()
        .select_related('item')
        .get(pk=incoming_transaction.pk)
    )
    return _create_transaction(locked_incoming, user)


@transaction.atomic
def create_transactions_for_matched_incoming(document, user):
    incoming_transactions = (
        IncomingTransaction.objects.select_for_update()
        .filter(
            document=document,
            is_deleted=False,
            transaction__isnull=True,
        )
        .select_related('item')
        .order_by('row_number')
    )
    created_transactions = []
    for incoming_transaction in incoming_transactions:
        if incoming_transaction.is_matched:
            created_transactions.append(
                _create_transaction(incoming_transaction, user)
            )
    return created_transactions


@transaction.atomic
def delete_pending_incoming_for_document(document):
    incoming_transactions = (
        IncomingTransaction.objects.all_with_deleted()
        .select_for_update()
        .filter(
            document=document,
            transaction__isnull=True,
            is_deleted=False,
        )
    )
    return incoming_transactions.update(is_deleted=True)


@transaction.atomic
def update_pending_incoming_report_date(document, report_date):
    return IncomingTransaction.objects.filter(
        document=document,
        is_deleted=False,
        transaction__isnull=True,
    ).update(report_date=report_date)
