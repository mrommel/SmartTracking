from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard', permanent=False), name='dashboard'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('reports', views.reports, name='reports'),
    path('releases', views.releases, name='releases'),
    # Authentication (Django's built-in login/logout views).
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
	path('projects/', views.project_list, name='project_list'),
	path('projects/<int:pk>/', views.project_detail, name='project_detail'),
	path('projects/<int:pk>/edit/', views.project_edit, name='project_edit'),
	path('projects/new/', views.project_create, name='project_create'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/bulk/', views.ticket_bulk_action, name='ticket_bulk_action'),
    path('tickets/new/', views.ticket_create, name='ticket_create'),
    path('tickets/<int:pk>/edit/', views.ticket_edit, name='ticket_edit'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/transition/', views.ticket_transition, name='ticket_transition'),
 	path('tickets/<int:pk>/sprint/', views.ticket_sprint_assign, name='ticket_sprint_assign'),
 	path('tickets/order/', views.update_backlog_order, name='update_backlog_order'),
    path('projects/<int:project_pk>/tickets/<int:pk>/delete/', views.ticket_delete, name='ticket_delete'),
    path('tickets/<int:pk>/relations/add/', views.ticket_relation_add, name='ticket_relation_add'),
    path('tickets/relations/<int:pk>/delete/', views.ticket_relation_delete, name='ticket_relation_delete'),
	path('tickets/<int:pk>/comment/', views.ticket_comment_create, name='ticket_comment_create'),
    path('tickets/comment/<int:pk>/edit/', views.ticket_comment_edit, name='ticket_comment_edit'),
    path('tickets/comment/<int:pk>/delete/', views.ticket_comment_delete, name='ticket_comment_delete'),
    path('tickets/<int:pk>/attach/', views.ticket_attachment_upload, name='ticket_attachment_upload'),
    path('tickets/<int:pk>/media/<int:attachment_pk>/', views.ticket_attachment_serve, name='ticket_attachment_serve'),
    path('tickets/attachments/<int:pk>/delete/', views.ticket_attachment_delete, name='ticket_attachment_delete'),
    # Label management (per-project).
    path('projects/<int:pk>/labels/', views.label_list, name='label_list'),
    path('labels/', views.label_list, name='label_list_all'),
    path('projects/<int:pk>/labels/new/', views.label_create, name='label_create'),
    path('labels/<int:pk>/edit/', views.label_update, name='label_update'),
    path('labels/<int:pk>/delete/', views.label_delete, name='label_delete'),
    # Component management (per-project).
    path('projects/<int:pk>/components/', views.component_list, name='component_list'),
    path('components/', views.component_list, name='component_list_all'),
    path('projects/<int:pk>/components/new/', views.component_create, name='component_create'),
	path('projects/<int:pk>/sprints/new/', views.sprint_create, name='sprint_create'),
	path('projects/<int:project_pk>/sprints/<int:sprint_pk>/edit/', views.sprint_edit, name='sprint_edit'),
	path('projects/<int:project_pk>/sprints/<int:sprint_pk>/close/', views.sprint_close, name='sprint_close'),
    path('components/<int:pk>/edit/', views.component_update, name='component_update'),
    path('components/<int:pk>/delete/', views.component_delete, name='component_delete'),
    # Version / release management.
    path('projects/<int:project_pk>/versions/new/', views.version_create, name='version_create'),
    path('projects/<int:project_pk>/roadmap/', views.version_roadmap, name='version_roadmap'),
    path('versions/<int:pk>/edit/', views.version_edit, name='version_edit'),
    path('versions/<int:pk>/delete/', views.version_delete, name='version_delete'),
    path('versions/<int:pk>/release_notes/', views.release_notes, name='release_notes'),
]

# JSON REST API for MCP integration (see tracking/api.py).
from django.urls import include  # noqa: E402

urlpatterns += [
    path('api/', include('tracking.api')),
]
