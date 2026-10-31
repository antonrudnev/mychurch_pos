from urllib.parse import urlencode

from directory.models import Item, ItemType
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction as db_transaction
from django.db.models import Exists, Max, OuterRef
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.generic import ListView, TemplateView

from .forms import (
    NewOpenListItemForm,
    NewProductTransactionForm,
    TransactionForm,
    TransactionManageForm,
)
from .models import Transaction


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
            Transaction.objects.select_related('item', 'item__item_type', 'cashier'),
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
        return render(
            request,
            self.template_name,
            {
                'transaction': self.transaction,
                'form': form,
                'transaction_list_url': self.get_transaction_list_url(request),
                'can_change_transaction': (
                    request.user.has_perm('transactions.change_transaction')
                    and not self.transaction.is_verified
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


class ItemTypeSelectView(PermissionRequiredMixin, ListView):
    model = ItemType
    template_name = 'transactions/item_type_select.html'
    context_object_name = 'item_types'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def get_queryset(self):
        return self.get_item_types(is_product_group=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_product_group_page'] = False
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


class ProductSearchView(PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/product_search.html'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = Item.objects.filter(
            item_type__is_product_group=True,
            is_active=True,
        ).select_related('item_type').order_by('name', 'item_type__name')
        selected_item_id = self.request.GET.get('item')
        context['items'] = items
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
    permission_required = 'transactions.add_transaction'
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


class TransactionCreateView(PermissionRequiredMixin, TemplateView):
    template_name = 'transactions/transaction_form.html'
    permission_required = 'transactions.add_transaction'
    raise_exception = True

    def get(self, request, *args, **kwargs):
        self.item_type = get_object_or_404(ItemType, pk=kwargs['item_type_id'])
        selected_item = None
        selected_item_id = request.GET.get('item')
        if selected_item_id is not None:
            selected_item = get_object_or_404(
                Item,
                pk=selected_item_id,
                item_type=self.item_type,
                is_active=True,
            )
        form = TransactionForm(
            item_type=self.item_type,
            selected_item=selected_item,
        )
        return self.render_form(request, form)

    def post(self, request, *args, **kwargs):
        self.item_type = get_object_or_404(ItemType, pk=kwargs['item_type_id'])
        form = TransactionForm(request.POST, item_type=self.item_type)
        if not form.is_valid():
            return self.render_form(request, form, status=400)

        transaction = form.save(commit=False)
        transaction.cashier = request.user
        transaction.is_verified = bool(self.request.user.has_perm('transactions.verify'))
        transaction.save()
        messages.success(request, 'Транзакция успешно создана.')
        return redirect('transactions:item_type_select')

    def render_form(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'item_type': self.item_type,
            },
            status=status,
        )
