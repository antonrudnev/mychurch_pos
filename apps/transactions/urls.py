from django.urls import path

from .views import (
    ItemTypeSelectView,
    NewOpenListItemView,
    NewProductTransactionView,
    ProductGroupSelectView,
    TransactionCreateView,
    TransactionHomeView,
    TransactionListView,
    TransactionManageView,
)

app_name = 'transactions'

urlpatterns = [
    path('', TransactionHomeView.as_view(), name='home'),
    path('mine/', TransactionListView.as_view(), name='transaction_list'),
    path(
        'mine/<int:transaction_id>/',
        TransactionManageView.as_view(),
        name='transaction_manage',
    ),
    path('types/', ItemTypeSelectView.as_view(), name='item_type_select'),
    path('types/products/', ProductGroupSelectView.as_view(), name='product_group_select'),
    path(
        'types/<int:item_type_id>/new-item/',
        NewOpenListItemView.as_view(),
        name='new_open_list_item',
    ),
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
