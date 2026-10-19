from directory.models import Item, ItemType
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction as db_transaction
from django.db.models import Exists, OuterRef
from django.utils.text import slugify
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, TemplateView

from .forms import NewProductTransactionForm, TransactionForm
from .models import Transaction


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
        if not self.request.user.is_superuser:
            queryset = queryset.filter(cashier=self.request.user)
        return queryset.order_by('-created_at')


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
                item_type_handle = 'other-product'
                item_type = ItemType.objects.filter(handle__iexact=item_type_handle).first()
                if item_type is None:
                    item_type = ItemType.objects.create(
                        name='Другие',
                        handle=item_type_handle,
                        is_product_group=True,
                    )
                elif not item_type.is_product_group:
                    item_type.is_product_group = True
                    item_type.save(update_fields=['is_product_group'])

                item = Item.objects.create(
                    item_type=item_type,
                    name=name,
                    handle=self.get_unique_item_handle(name),
                    price=form.cleaned_data['price'],
                    is_active=form.cleaned_data['keep_active'],
                )

            Transaction.objects.create(
                item=item,
                price=form.cleaned_data['price'],
                quantity=form.cleaned_data['quantity'],
                cashier=request.user,
            )

        messages.success(request, 'Транзакция успешно создана.')
        return redirect('transactions:product_group_select')

    def get_unique_item_handle(self, name):
        base_handle = slugify(name, allow_unicode=True)[:100] or 'product'
        handle = base_handle
        suffix = 2
        while Item.objects.filter(handle=handle).exists():
            suffix_text = f'-{suffix}'
            handle = f'{base_handle[:100 - len(suffix_text)]}{suffix_text}'
            suffix += 1
        return handle

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
