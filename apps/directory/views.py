from django.db.models import Exists, OuterRef, Q
from django.contrib.auth.mixins import PermissionRequiredMixin
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, TemplateView

from .models import Item, ItemType


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ('item_type', 'name', 'price', 'order_number')
        widgets = {
            'item_type': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
            }),
            'order_number': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
        }

    def __init__(
        self,
        *args,
        can_change_item=True,
        can_change_item_price=False,
        can_change_item_type=True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if not can_change_item:
            self.fields['name'].disabled = True
            self.fields['order_number'].disabled = True
            self.fields['price'].disabled = not can_change_item_price
        if not can_change_item_type:
            self.fields.pop('item_type')


class ItemTypeListView(PermissionRequiredMixin, ListView):
    model = ItemType
    template_name = 'directory/item_type_list.html'
    context_object_name = 'item_types'
    permission_required = 'directory.view_itemtype'
    raise_exception = True

    def get_queryset(self):
        nonzero_price_items = Item.objects.filter(
            item_type_id=OuterRef('pk'),
            price__isnull=False,
        ).exclude(price=0)
        return (
            ItemType.objects
            .annotate(has_nonzero_price_items=Exists(nonzero_price_items))
            .filter(Q(is_product_group=True) | Q(has_nonzero_price_items=True))
            .order_by('order_number', 'name')
        )


class ItemTypeDetailView(PermissionRequiredMixin, ListView):
    model = Item
    template_name = 'directory/item_type_detail.html'
    context_object_name = 'items'
    permission_required = 'directory.view_itemtype'
    raise_exception = True
    paginate_by = 5

    def get_item_type(self):
        if not hasattr(self, 'item_type'):
            self.item_type = get_object_or_404(ItemType, pk=self.kwargs['pk'])
        return self.item_type

    def get_queryset(self):
        return (
            Item.objects
            .filter(item_type=self.get_item_type())
            .filter(price__isnull=False)
            .exclude(price=0)
            .select_related('item_type')
            .order_by('order_number', 'name')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_type'] = self.get_item_type()
        return context


class ItemDetailView(PermissionRequiredMixin, TemplateView):
    template_name = 'directory/item_detail.html'
    permission_required = 'directory.view_item'
    raise_exception = True

    def dispatch(self, request, *args, **kwargs):
        self.item = get_object_or_404(
            Item.objects.select_related('item_type'),
            pk=kwargs['pk'],
        )
        self.origin_item_type_id = self.item.item_type_id
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self.render_page(
            request,
            self.get_form(request, instance=self.item),
        )

    def get_form(self, request, **kwargs):
        return ItemForm(
            can_change_item=request.user.has_perm('directory.change_item'),
            can_change_item_price=request.user.has_perm(
                'directory.change_item_price'
            ),
            can_change_item_type=request.user.has_perm(
                'directory.change_itemtype'
            ),
            **kwargs,
        )

    def get_item_list_url(self, request):
        list_url = reverse(
            'directory:item_type_detail',
            args=[self.origin_item_type_id],
        )
        page = request.GET.get('page')
        if page and page.isdecimal() and len(page) <= 9:
            return f'{list_url}?page={page}'
        return list_url

    def get_item_detail_url(self, request):
        detail_url = reverse('directory:item_detail', args=[self.item.pk])
        page = request.GET.get('page')
        if page and page.isdecimal() and len(page) <= 9:
            return f'{detail_url}?page={page}'
        return detail_url

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'save':
            if not (
                request.user.has_perm('directory.change_item')
                or request.user.has_perm('directory.change_item_price')
            ):
                raise PermissionDenied
            form = self.get_form(
                request,
                data=request.POST,
                instance=self.item,
            )
            if not form.is_valid():
                return self.render_page(request, form, status=400)
            form.save()
            messages.success(request, 'Позиция справочника изменена.')
            return redirect(self.get_item_list_url(request))

        if action == 'toggle_active':
            if not request.user.has_perm('directory.delete_item'):
                raise PermissionDenied
            self.item.is_active = not self.item.is_active
            self.item.save(update_fields=['is_active'])
            messages.success(
                request,
                'Позиция активирована.' if self.item.is_active else 'Позиция деактивирована.',
            )
            return redirect(self.get_item_detail_url(request))

        raise PermissionDenied

    def render_page(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {
                'item': self.item,
                'form': form,
                'item_list_url': self.get_item_list_url(request),
                'can_edit_item': (
                    request.user.has_perm('directory.change_item')
                    or request.user.has_perm('directory.change_item_price')
                ),
                'can_change_item': request.user.has_perm(
                    'directory.change_item'
                ),
                'can_change_item_type': request.user.has_perm(
                    'directory.change_itemtype'
                ),
            },
            status=status,
        )
