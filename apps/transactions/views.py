from directory.models import Item, ItemType
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction as db_transaction
from django.db.models import Exists, Max, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
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

    def get_queryset(self):
        queryset = Transaction.objects.select_related(
            'item',
            'item__item_type',
            'cashier',
        )
        if (not self.request.user.has_perm('transactions.view_all_transactions')):
            queryset = queryset.filter(cashier=self.request.user)
        return queryset.order_by('-created_at')


class TransactionManageView(TemplateView):
    template_name = 'transactions/transaction_manage.html'

    def dispatch(self, request, *args, **kwargs):
        self.transaction = get_object_or_404(
            Transaction.objects.select_related('item', 'item__item_type', 'cashier'),
            pk=kwargs['transaction_id'],
        )
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
            if not request.user.has_perm('transactions.change_transaction'):
                raise PermissionDenied
            form = TransactionManageForm(request.POST, instance=self.transaction)
            if not form.is_valid():
                return self.render_page(request, form, status=400)
            form.save()
            messages.success(request, 'Транзакция изменена.')
            return redirect('transactions:transaction_list')

        if action == 'delete':
            if not request.user.has_perm('transactions.delete_transaction'):
                raise PermissionDenied
            self.transaction.delete_soft()
            messages.success(request, 'Транзакция удалена.')
            return redirect('transactions:transaction_list')

        if action == 'toggle_verification':
            if not request.user.has_perm('transactions.verify_transaction'):
                raise PermissionDenied
            self.transaction.is_verified = not self.transaction.is_verified
            self.transaction.verified_by = (
                request.user if self.transaction.is_verified else None
            )
            self.transaction.save(update_fields=['is_verified', 'verified_by'])
            messages.success(
                request,
                'Транзакция подтверждена.'
                if self.transaction.is_verified
                else 'Подтверждение транзакции снято.',
            )
            return redirect(
                'transactions:transaction_manage',
                transaction_id=self.transaction.pk,
            )

        raise PermissionDenied

    def render_page(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {
                'transaction': self.transaction,
                'form': form,
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
        form = TransactionForm(item_type=self.item_type)
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
