from django.urls import path

from .views import (
    ItemTypeSelectView,
    NewProductTransactionView,
    ProductGroupSelectView,
    TransactionCreateView,
    TransactionHomeView,
    TransactionListView,
)

app_name = 'transactions'

urlpatterns = [
    path('', TransactionHomeView.as_view(), name='home'),
    path('mine/', TransactionListView.as_view(), name='transaction_list'),
    path('types/', ItemTypeSelectView.as_view(), name='item_type_select'),
    path('types/products/', ProductGroupSelectView.as_view(), name='product_group_select'),
    path(
        'types/products/new/',
        NewProductTransactionView.as_view(),
        name='new_product_transaction',
    ),
    path(
        'types/<int:item_type_id>/new/',
        TransactionCreateView.as_view(),
        name='transaction_create',
    ),
]
