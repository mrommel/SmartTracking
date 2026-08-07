from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard', permanent=False), name='dashboard'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('projects/', views.project_list, name='project_list'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/new/', views.ticket_create, name='ticket_create'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/transition/', views.ticket_transition, name='ticket_transition'),
]