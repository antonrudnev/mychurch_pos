from django.urls import path

from .views import (
    ItemTypeSelectView,
    TransactionCreateView,
    TransactionHomeView,
    TransactionListView,
)

app_name = 'transactions'

urlpatterns = [
    path('', TransactionHomeView.as_view(), name='home'),
    path('mine/', TransactionListView.as_view(), name='transaction_list'),
    path('types/', ItemTypeSelectView.as_view(), name='item_type_select'),
    path(
        'types/<int:item_type_id>/new/',
        TransactionCreateView.as_view(),
        name='transaction_create',
    ),
]
