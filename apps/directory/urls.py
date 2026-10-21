from django.urls import path

from .views import ItemDetailView, ItemTypeDetailView, ItemTypeListView

app_name = 'directory'

urlpatterns = [
    path('', ItemTypeListView.as_view(), name='home'),
    path('types/<int:pk>/', ItemTypeDetailView.as_view(), name='item_type_detail'),
    path('items/<int:pk>/', ItemDetailView.as_view(), name='item_detail'),
]
