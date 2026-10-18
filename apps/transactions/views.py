from directory.models import Item, ItemType
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, TemplateView

from .forms import TransactionForm
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
        available_items = Item.objects.filter(
            item_type_id=OuterRef('pk'),
            is_active=True,
        )
        return ItemType.objects.annotate(
            has_items=Exists(available_items),
        ).order_by('order_number', 'name')


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
