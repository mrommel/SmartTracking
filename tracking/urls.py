from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard', permanent=False), name='dashboard'),
    path('dashboard', views.dashboard, name='dashboard'),
    # Authentication (Django's built-in login/logout views).
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('projects/', views.project_list, name='project_list'),
    path('projects/new/', views.project_create, name='project_create'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/new/', views.ticket_create, name='ticket_create'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/transition/', views.ticket_transition, name='ticket_transition'),
]

# JSON REST API for MCP integration (see tracking/api.py).
from django.urls import include  # noqa: E402

urlpatterns += [
    path('api/', include('tracking.api')),
]
