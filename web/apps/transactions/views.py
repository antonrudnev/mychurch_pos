from urllib.parse import urlencode

from directory.models import Item, ItemType
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.db.models import Exists, Max, OuterRef, Prefetch
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.generic import ListView, TemplateView

from .forms import (
    DATE_FIELD_ITEM_HANDLES,
    IncomingTransactionReviewForm,
    NewOpenListItemForm,
    NewProductTransactionForm,
    TransactionForm,
    TransactionManageForm,
)
from .models import IncomingTransaction, Transaction
from integrations.models import IncomingDocument
from .services.incoming_review import (
    create_transaction_for_incoming,
    create_transactions_for_matched_incoming,
)


def get_unique_item_handle(name):
    base_handle = slugify(name, allow_unicode=True)[:100] or 'product'
    handle = base_handle
    suffix = 2
    while Item.objects.filter(handle=handle).exists():
        suffix_text = f'-{suffix}'
        handle = f'{base_handle[:100 - len(suffix_text)]}{suffix_text}'
        suffix += 1
    return handle


def get_review_preset(request):
    preset = request.GET.get('preset', 'custom')
    if preset not in {'week', 'last-week', '3', '5', 'custom'}:
        return 'custom'
    return preset


def get_review_report_handle(request):
    report_handle = request.GET.get('report_handle', 'cash-report')
    if report_handle not in {'cash-report', 'product-report'}:
        return 'cash-report'
    return report_handle


class TransactionHomeView(PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/transaction_home.html'
    permission_required = 'transactions.view_transaction'
    raise_exception = True

    def has_permission(self):
        return any(
            self.request.user.has_perm(permission)
            for permission in (
                'transactions.view_transaction',
                'transactions.add_transaction',
                'transactions.verify_transaction',
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if (
            self.request.user.has_perm('transactions.add_transaction')
            or self.request.user.has_perm('transactions.verify_transaction')
        ):
            pending = IncomingTransaction.objects.filter(transaction__isnull=True)
            context['incoming_transactions_count'] = pending.count()
            context['incoming_documents_count'] = (
                pending.values('document_id').distinct().count()
            )
        else:
            context['incoming_transactions_count'] = 0
            context['incoming_documents_count'] = 0
        return context


class IncomingReviewPermissionMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (
            request.user.has_perm('transactions.add_transaction')
            or request.user.has_perm('transactions.verify_transaction')
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class IncomingDocumentsView(IncomingReviewPermissionMixin, ListView):
    template_name = 'transactions/incoming_documents.html'
    context_object_name = 'documents'

    def get_queryset(self):
        active_rows = IncomingTransaction.objects.filter(is_deleted=False)
        pending_rows = active_rows.filter(transaction__isnull=True).select_related('item')
        return (
            IncomingDocument.objects.filter(
                incoming_transactions__is_deleted=False,
                incoming_transactions__transaction__isnull=True,
            )
            .distinct()
            .prefetch_related(
                Prefetch(
                    'incoming_transactions',
                    queryset=active_rows.select_related('item'),
                    to_attr='active_incoming_rows',
                ),
                Prefetch(
                    'incoming_transactions',
                    queryset=pending_rows,
                    to_attr='pending_incoming_rows',
                ),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for document in context['documents']:
            active_rows = document.active_incoming_rows
            pending_rows = document.pending_incoming_rows
            document.incoming_total = sum(
                (row.total_cost for row in active_rows),
                start=0,
            )
            document.incoming_total_count = len(active_rows)
            document.incoming_pending_count = len(pending_rows)
            document.incoming_manual_review_count = sum(
                not row.is_matched for row in pending_rows
            )
        return context


class IncomingDocumentView(IncomingReviewPermissionMixin, TemplateView):
    template_name = 'transactions/incoming_document.html'

    def get_document(self):
        if not hasattr(self, '_incoming_document'):
            self._incoming_document = get_object_or_404(
                IncomingDocument,
                pk=self.kwargs['document_id'],
            )
        return self._incoming_document

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.get_document()
        rows = list(
            document.incoming_transactions.filter(
                transaction__isnull=True,
            )
            .select_related('item', 'item__item_type')
            .order_by('row_number')
        )
        for row in rows:
            row.review_reasons = get_incoming_review_reasons(row)
        active_rows = document.incoming_transactions.all()
        context.update({
            'document': document,
            'incoming_rows': rows,
            'document_total': sum(
                (row.total_cost for row in active_rows),
                start=0,
            ),
            'matched_rows_count': sum(row.is_matched for row in rows),
        })
        return context

    def post(self, request, *args, **kwargs):
        document = self.get_document()
        if request.POST.get('action') != 'add_matched':
            raise PermissionDenied
        try:
            created = create_transactions_for_matched_incoming(
                document,
                request.user,
            )
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return redirect('transactions:incoming_document', document_id=document.pk)

        messages.success(
            request,
            f'Добавлено транзакций: {len(created)}.',
        )
        if IncomingTransaction.objects.filter(
            document=document,
            transaction__isnull=True,
        ).exists():
            return redirect('transactions:incoming_document', document_id=document.pk)
        return redirect('transactions:incoming_documents')


class IncomingTransactionDetailView(IncomingReviewPermissionMixin, TemplateView):
    template_name = 'transactions/incoming_transaction_detail.html'

    def get_incoming_transaction(self):
        if not hasattr(self, '_incoming_transaction'):
            self._incoming_transaction = get_object_or_404(
                IncomingTransaction.objects.select_related(
                    'document',
                    'item',
                    'item__item_type',
                    'transaction',
                ),
                pk=self.kwargs['pk'],
            )
        return self._incoming_transaction

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        incoming_transaction = self.get_incoming_transaction()
        incoming_transaction.review_reasons = get_incoming_review_reasons(
            incoming_transaction
        )
        incoming_transaction.match_checks = get_incoming_match_checks(
            incoming_transaction
        )
        can_create_transaction = (
            not incoming_transaction.is_processed
            and (
                self.request.user.has_perm('transactions.add_transaction')
                or self.request.user.has_perm('transactions.verify_transaction')
            )
        )
        context.update({
            'incoming_transaction': incoming_transaction,
            'form': kwargs.get(
                'form',
                IncomingTransactionReviewForm(instance=incoming_transaction),
            ),
            'can_create_transaction': can_create_transaction,
            'transaction_create_url': (
                reverse(
                    'transactions:transaction_create',
                    args=[incoming_transaction.item.item_type_id],
                )
                + f'?incoming_transaction={incoming_transaction.pk}'
                if (
                    can_create_transaction
                    and incoming_transaction.item_id
                    and incoming_transaction.item.is_active
                )
                else (
                    f"{reverse('transactions:item_type_select')}"
                    f"?incoming_transaction={incoming_transaction.pk}"
                    if can_create_transaction
                    else ''
                )
            ),
        })
        return context

    def post(self, request, *args, **kwargs):
        incoming_transaction = self.get_incoming_transaction()
        if incoming_transaction.is_processed:
            raise PermissionDenied

        action = request.POST.get('action')
        if action == 'delete':
            incoming_transaction.delete_soft()
            messages.success(request, 'Входящая строка удалена.')
            return redirect(
                'transactions:incoming_document',
                document_id=incoming_transaction.document_id,
            )
        if action != 'save':
            raise PermissionDenied

        form = IncomingTransactionReviewForm(
            request.POST,
            instance=incoming_transaction,
        )
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form),
                status=400,
            )
        form.save()
        messages.success(request, 'Входящая строка сохранена.')
        return redirect(
            'transactions:incoming_transaction_detail',
            pk=incoming_transaction.pk,
        )


def get_incoming_review_reasons(incoming_transaction):
    reasons = []
    checks = get_incoming_match_checks(incoming_transaction)
    if not checks['item']:
        reasons.append('Товар не найден в справочнике.')
    raw_counts = incoming_transaction.raw_counts
    if not isinstance(raw_counts, list) or not raw_counts:
        total = (
            checks['raw_counts_sum']
            if checks['raw_counts_sum'] is not None
            else 'не вычислена'
        )
        reasons.append(f'Ряд количеств не распознан (сумма: {total}).')
    elif not checks['counts']:
        if checks['raw_counts_sum'] is None:
            reasons.append('Распознанный ряд количеств некорректен; сумму вычислить нельзя.')
        else:
            reasons.append(
                f"Сумма распознанных количеств ({checks['raw_counts_sum']}) "
                f"не совпадает с количеством ({incoming_transaction.quantity})."
            )
    if checks['item'] and not checks['price']:
        reasons.append('Цена не совпадает с ценой в справочнике.')
    return reasons


def get_incoming_match_checks(incoming_transaction):
    item_matches = incoming_transaction.item_id is not None
    raw_counts_sum = None
    raw_counts = incoming_transaction.raw_counts
    if isinstance(raw_counts, list):
        try:
            raw_counts_sum = sum(int(value) for value in raw_counts)
        except (OverflowError, TypeError, ValueError):
            raw_counts_sum = None
    counts_match = (
        bool(raw_counts)
        and raw_counts_sum is not None
        and raw_counts_sum == incoming_transaction.quantity
    )
    return {
        'item': item_matches,
        'counts': counts_match,
        'raw_counts_sum': raw_counts_sum,
        'price': (
            item_matches
            and incoming_transaction.item.price == incoming_transaction.price
        ),
    }

class TransactionListView(PermissionRequiredMixin, ListView):
    model = Transaction
    template_name = 'transactions/transaction_list.html'
    context_object_name = 'transactions'
    permission_required = 'transactions.view_transaction'
    raise_exception = True
    paginate_by = 5

    def has_permission(self):
        if self.request.user.has_perm('transactions.view_transaction'):
            return True
        return (
            self.request.GET.get('unverified') == '1'
            and (
                self.request.user.has_perm('transactions.verify_transaction')
                or self.request.user.has_perm('reports.add_report')
            )
        )

    def get_queryset(self):
        queryset = Transaction.objects.select_related(
            'item',
            'item__item_type',
            'cashier',
        )
        if getattr(self, 'is_verification_review', False):
            queryset = queryset.filter(
                is_verified=False,
                created_at__date__range=(self.date_from, self.date_to),
            )
            if self.request.user.has_perm('transactions.verify_transaction'):
                return queryset.order_by('-created_at')
        if (not self.request.user.has_perm('transactions.view_all_transactions')):
            queryset = queryset.filter(cashier=self.request.user)
        return queryset.order_by('-created_at')

    def get(self, request, *args, **kwargs):
        self.is_verification_review = request.GET.get('unverified') == '1'
        if self.is_verification_review:
            if not (
                request.user.has_perm('transactions.verify_transaction')
                or request.user.has_perm('reports.add_report')
            ):
                raise PermissionDenied
            self.date_from = parse_date(request.GET.get('date_from', ''))
            self.date_to = parse_date(request.GET.get('date_to', ''))
            if (
                self.date_from is None
                or self.date_to is None
                or self.date_from > self.date_to
            ):
                return HttpResponseBadRequest('A valid transaction date range is required.')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_verification_review'] = self.is_verification_review
        if self.is_verification_review:
            context['date_from'] = self.date_from
            context['date_to'] = self.date_to
            context['period_preset'] = get_review_preset(self.request)
            context['report_handle'] = get_review_report_handle(self.request)
            context['can_proceed_report'] = (
                self.request.user.has_perm('transactions.verify_transaction')
                and self.request.user.has_perm('reports.add_report')
            )
            proceed_report_query = urlencode({
                'date_from': self.date_from.isoformat(),
                'date_to': self.date_to.isoformat(),
                'preset': context['period_preset'],
                'skip_unverified_check': '1',
                'report_handle': context['report_handle'],
            })
            context['proceed_report_url'] = (
                f"{reverse('reports:generate_report', args=[context['report_handle']])}?"
                f"{proceed_report_query}"
            )
            context['report_return_url'] = (
                f"{reverse('reports:generate_report', args=[context['report_handle']])}?"
                f"{urlencode({
                    'select_period': '1',
                    'preserve_dates': '1',
                    'preset': context['period_preset'],
                    'date_from': self.date_from.isoformat(),
                    'date_to': self.date_to.isoformat(),
                    'report_handle': context['report_handle'],
                })}"
            )
        return context

class TransactionManageView(TemplateView):
    template_name = 'transactions/transaction_manage.html'

    def get_transaction_list_url(self, request):
        query = self.get_review_query(request)
        if query:
            return f"{reverse('transactions:transaction_list')}?{query}"
        page = request.GET.get('page')
        if page and page.isdecimal() and len(page) <= 9:
            return f"{reverse('transactions:transaction_list')}?{urlencode({'page': page})}"
        return reverse('transactions:transaction_list')

    def get_review_query(self, request):
        if request.GET.get('unverified') != '1':
            return ''
        date_from = parse_date(request.GET.get('date_from', ''))
        date_to = parse_date(request.GET.get('date_to', ''))
        if date_from is None or date_to is None or date_from > date_to:
            return ''
        query = {
            'unverified': '1',
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'preset': get_review_preset(request),
            'report_handle': get_review_report_handle(request),
        }
        page = request.GET.get('page')
        if page and page.isdecimal() and len(page) <= 9:
            query['page'] = page
        return urlencode(query)

    def can_manage_transaction(self, user):
        return (
            not self.transaction.is_verified
            or user.has_perm('transactions.verify_transaction')
        )

    def dispatch(self, request, *args, **kwargs):
        self.transaction = get_object_or_404(
            Transaction.objects.select_related('item', 'item__item_type', 'cashier', 'verified_by'),
            pk=kwargs['transaction_id'],
        )

        is_report_review = (
            request.GET.get('unverified') == '1'
            and request.user.has_perm('reports.add_report')
            and not self.transaction.is_verified
        )
        if is_report_review:
            date_from = parse_date(request.GET.get('date_from', ''))
            date_to = parse_date(request.GET.get('date_to', ''))
            is_report_review = (
                date_from is not None
                and date_to is not None
                and date_from <= date_to
                and date_from <= self.transaction.created_at.date() <= date_to
            )

        if (
            not request.user.has_perm('transactions.view_transaction')
            and not is_report_review
        ):
            raise PermissionDenied

        can_view_all = (
            request.user.has_perm('transactions.view_all_transactions')
            or request.user.has_perm('transactions.verify_transaction')
        )
        if self.transaction.cashier_id != request.user.pk and not can_view_all:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self.render_page(request, TransactionManageForm(instance=self.transaction))

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'save':
            if (
                not request.user.has_perm('transactions.change_transaction')
                or self.transaction.is_verified
            ):
                raise PermissionDenied
            form = TransactionManageForm(request.POST, instance=self.transaction)
            if not form.is_valid():
                return self.render_page(request, form, status=400)
            form.save()
            messages.success(request, 'Транзакция изменена.')
            return redirect(self.get_transaction_list_url(request))

        if action == 'delete':
            if (
                not request.user.has_perm('transactions.delete_transaction')
                or not self.can_manage_transaction(request.user)
            ):
                raise PermissionDenied
            self.transaction.delete_soft()
            messages.success(request, 'Транзакция удалена.')
            return redirect(self.get_transaction_list_url(request))

        if action == 'save_and_verify':
            if (
                not request.user.has_perm('transactions.verify_transaction')
                or not request.user.has_perm('transactions.change_transaction')
                or self.transaction.is_verified
            ):
                raise PermissionDenied

            form = TransactionManageForm(request.POST, instance=self.transaction)
            if not form.is_valid():
                return self.render_page(request, form, status=400)

            self.transaction = form.save(commit=False)
            self.transaction.is_verified = True
            self.transaction.verified_by = request.user
            self.transaction.save()
            form.save_m2m()
            messages.success(request, 'Транзакция подтверждена.')
            return redirect(self.get_transaction_list_url(request))

        if action == 'toggle_verification':
            if not request.user.has_perm('transactions.verify_transaction'):
                raise PermissionDenied

            if (
                not self.transaction.is_verified
                and request.user.has_perm('transactions.change_transaction')
            ):
                form = TransactionManageForm(
                    request.POST,
                    instance=self.transaction,
                )
                if not form.is_valid():
                    return self.render_page(request, form, status=400)
                self.transaction = form.save(commit=False)

            self.transaction.is_verified = not self.transaction.is_verified
            self.transaction.verified_by = (
                request.user if self.transaction.is_verified else None
            )
            self.transaction.save()
            messages.success(
                request,
                'Транзакция подтверждена.'
                if self.transaction.is_verified
                else 'Подтверждение транзакции снято.',
            )
            manage_url = reverse(
                'transactions:transaction_manage',
                args=[self.transaction.pk],
            )
            review_query = self.get_review_query(request)
            if not review_query:
                page = request.GET.get('page')
                if page and page.isdecimal() and len(page) <= 9:
                    review_query = urlencode({'page': page})
            if review_query:
                manage_url = f'{manage_url}?{review_query}'
            return redirect(manage_url)

        raise PermissionDenied

    def render_page(self, request, form, status=200):
        can_change_transaction = (
            request.user.has_perm('transactions.change_transaction')
            and not self.transaction.is_verified
        )
        return render(
            request,
            self.template_name,
            {
                'transaction': self.transaction,
                'form': form,
                'transaction_list_url': self.get_transaction_list_url(request),
                'can_change_transaction': can_change_transaction,
                'can_edit_transaction_datetime': (
                    can_change_transaction
                    and self.transaction.item.handle in DATE_FIELD_ITEM_HANDLES
                ),
                'can_view_all_transactions': request.user.has_perm(
                    'transactions.view_all_transactions'
                ),
                'can_delete_transaction': (
                    request.user.has_perm('transactions.delete_transaction')
                    and self.can_manage_transaction(request.user)
                ),
            },
            status=status,
        )


class ItemTypeSelectView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = ItemType
    template_name = 'transactions/item_type_select.html'
    context_object_name = 'item_types'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def has_permission(self):
        if self.request.GET.get('incoming_transaction'):
            return (
                self.request.user.has_perm('transactions.add_transaction')
                or self.request.user.has_perm('transactions.verify_transaction')
            )
        return super().has_permission()

    def get_queryset(self):
        return self.get_item_types(is_product_group=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_product_group_page'] = False
        context['incoming_transaction_id'] = self.request.GET.get(
            'incoming_transaction',
            '',
        )
        return context

    def get_item_types(self, *, is_product_group):
        available_items = Item.objects.filter(
            item_type_id=OuterRef('pk'),
            is_active=True,
        )
        return ItemType.objects.filter(
            is_product_group=is_product_group,
        ).annotate(
            has_items=Exists(available_items),
        ).order_by('order_number', 'name')


class ProductGroupSelectView(ItemTypeSelectView):
    def get_queryset(self):
        return self.get_item_types(is_product_group=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_product_group_page'] = True
        return context


class ProductSearchView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/product_search.html'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def has_permission(self):
        if self.request.GET.get('incoming_transaction'):
            return (
                self.request.user.has_perm('transactions.add_transaction')
                or self.request.user.has_perm('transactions.verify_transaction')
            )
        return super().has_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = Item.objects.filter(
            item_type__is_product_group=True,
            is_active=True,
        ).select_related('item_type').order_by('name', 'item_type__name')
        selected_item_id = self.request.GET.get('item')
        context['items'] = items
        incoming_id = self.request.GET.get('incoming_transaction', '')
        context['incoming_transaction_id'] = (
            incoming_id if incoming_id.isdecimal() else ''
        )
        context['selected_item'] = (
            get_object_or_404(items, pk=selected_item_id)
            if selected_item_id is not None
            else None
        )
        selected_item = context['selected_item']
        if selected_item is not None:
            if selected_item.price is None:
                context['selected_item_price'] = 'Не указана'
            elif selected_item.price == 0:
                context['selected_item_price'] = 'Сумма по запросу'
            else:
                context['selected_item_price'] = f'{selected_item.price} руб.'
        return context


class NewOpenListItemView(PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/new_open_list_item.html'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def dispatch(self, request, *args, **kwargs):
        self.item_type = get_object_or_404(
            ItemType,
            pk=kwargs['item_type_id'],
            is_open_list=True,
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self.render_form(request, NewOpenListItemForm())

    def post(self, request, *args, **kwargs):
        form = NewOpenListItemForm(request.POST)
        if not form.is_valid():
            return self.render_form(request, form, status=400)

        name = form.cleaned_data['name']
        price = form.cleaned_data['price']
        with db_transaction.atomic():
            normalized_name = name.casefold()
            item = next(
                (
                    candidate
                    for candidate in Item.objects.filter(
                        item_type=self.item_type,
                        is_active=True,
                    ).order_by('pk').iterator()
                    if candidate.name.casefold() == normalized_name
                ),
                None,
            )
            if item is None:
                item = Item.objects.create(
                    item_type=self.item_type,
                    name=name,
                    handle=get_unique_item_handle(name),
                    price=price,
                )
            elif item.price != price:
                item.price = price
                item.save(update_fields=['price'])

            Transaction.objects.create(
                item=item,
                price=price,
                cashier=request.user,
                is_verified = bool(self.request.user.has_perm('transactions.verify'))
            )

        messages.success(request, 'Транзакция успешно создана.')
        return redirect(
            'transactions:product_group_select'
            if self.item_type.is_product_group
            else 'transactions:item_type_select'
        )

    def get_recent_item_names(self):
        return (
            Transaction.objects
            .filter(item__item_type=self.item_type)
            .values('item__name')
            .annotate(last_used=Max('created_at'))
            .order_by('-last_used', 'item__name')
            .values_list('item__name', flat=True)[:30]
        )

    def render_form(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'item_type': self.item_type,
                'recent_item_names': self.get_recent_item_names(),
            },
            status=status,
        )


class NewProductTransactionView(PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/new_product_transaction.html'
    permission_required = ('transactions.add_transaction', 'directory.add_item')
    raise_exception = True

    def get(self, request, *args, **kwargs):
        return self.render_form(request, NewProductTransactionForm())

    def post(self, request, *args, **kwargs):
        form = NewProductTransactionForm(request.POST)
        if not form.is_valid():
            return self.render_form(request, form, status=400)

        with db_transaction.atomic():
            name = form.cleaned_data['name'].strip()
            normalized_name = name.casefold()
            item = next(
                (
                    candidate
                    for candidate in Item.objects.only('id', 'name', 'item_type_id').iterator()
                    if candidate.name.casefold() == normalized_name
                ),
                None,
            )
            if item is None:
                item_type_handle = 'product-other'
                item_type = ItemType.objects.filter(handle__iexact=item_type_handle).first()
                if item_type is None:
                    item_type = ItemType.objects.create(
                        name='Прочие товары',
                        handle=item_type_handle,
                        is_product_group=True,
                        order_number = 1000
                    )
                elif not item_type.is_product_group:
                    item_type.is_product_group = True
                    item_type.save(update_fields=['is_product_group'])

                item = Item.objects.create(
                    item_type=item_type,
                    name=name,
                    handle=get_unique_item_handle(name),
                    price=form.cleaned_data['price'],
                    is_active=form.cleaned_data['keep_active'],
                )

            Transaction.objects.create(
                item=item,
                price=form.cleaned_data['price'],
                quantity=form.cleaned_data['quantity'],
                cashier=request.user,
                is_verified = bool(self.request.user.has_perm('transactions.verify'))
            )

        messages.success(request, 'Транзакция успешно создана.')
        return redirect('transactions:product_group_select')

    def render_form(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {'form': form},
            status=status,
        )


class TransactionCreateView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/transaction_form.html'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def has_permission(self):
        if self.request.GET.get('incoming_transaction') or self.request.POST.get(
            'incoming_transaction'
        ):
            return (
                self.request.user.has_perm('transactions.add_transaction')
                or self.request.user.has_perm('transactions.verify_transaction')
            )
        return self.request.user.has_perm('transactions.add_transaction')

    def get_incoming_transaction(self):
        incoming_id = self.request.GET.get('incoming_transaction')
        if incoming_id is None:
            incoming_id = self.request.POST.get('incoming_transaction')
        if incoming_id is None:
            return None
        incoming_transaction = get_object_or_404(
            IncomingTransaction.objects.select_related('item'),
            pk=incoming_id,
            transaction__isnull=True,
        )
        if (
            incoming_transaction.item_id
            and incoming_transaction.item.item_type_id != self.item_type.pk
        ):
            raise PermissionDenied
        return incoming_transaction

    def get(self, request, *args, **kwargs):
        self.item_type = get_object_or_404(ItemType, pk=kwargs['item_type_id'])
        incoming_transaction = self.get_incoming_transaction()
        selected_item = None
        selected_item_id = request.GET.get('item')
        if (
            incoming_transaction
            and incoming_transaction.item_id
            and incoming_transaction.item.is_active
        ):
            selected_item = incoming_transaction.item
        elif selected_item_id is not None:
            selected_item = get_object_or_404(
                Item,
                pk=selected_item_id,
                item_type=self.item_type,
                is_active=True,
            )
        form = TransactionForm(
            item_type=self.item_type,
            selected_item=selected_item,
            incoming_transaction=incoming_transaction,
        )
        return self.render_form(request, form, incoming_transaction=incoming_transaction)

    def post(self, request, *args, **kwargs):
        self.item_type = get_object_or_404(ItemType, pk=kwargs['item_type_id'])
        incoming_transaction = self.get_incoming_transaction()
        form = TransactionForm(
            request.POST,
            item_type=self.item_type,
            incoming_transaction=incoming_transaction,
        )
        if not form.is_valid():
            return self.render_form(
                request,
                form,
                incoming_transaction=incoming_transaction,
                status=400,
            )

        transaction = form.save(commit=False)
        if incoming_transaction is not None:
            try:
                create_transaction_for_incoming(
                    incoming_transaction,
                    request.user,
                    transaction_record=transaction,
                )
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return redirect(
                    'transactions:incoming_transaction_detail',
                    pk=incoming_transaction.pk,
                )
            messages.success(request, 'Транзакция создана из входящей строки.')
            return redirect(
                'transactions:incoming_document',
                document_id=incoming_transaction.document_id,
            )

        with db_transaction.atomic():
            transaction.cashier = request.user
            transaction.is_verified = request.user.has_perm(
                'transactions.verify_transaction'
            )
            transaction.verified_by = (
                request.user if transaction.is_verified else None
            )
            transaction.save()
        messages.success(request, 'Транзакция успешно создана.')
        return redirect('transactions:item_type_select')

    def render_form(
        self,
        request,
        form,
        incoming_transaction=None,
        status=200,
    ):
        return_url = (
            reverse(
                'transactions:incoming_transaction_detail',
                args=[incoming_transaction.pk],
            )
            if incoming_transaction
            else (
                (
                    f"{reverse('transactions:product_search')}?"
                    f"{urlencode({'item': request.GET['item']})}"
                )
                if request.GET.get('item')
                else (
                    reverse('transactions:product_group_select')
                    if self.item_type.is_product_group
                    else reverse('transactions:item_type_select')
                )
            )
        )
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'item_type': self.item_type,
                'incoming_transaction': incoming_transaction,
                'return_url': return_url,
            },
            status=status,
        )
