from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.views.generic import RedirectView

import tracking.views.project_views as _pv
import tracking.views.ticket_views as _tv
import tracking.views.sprint_views as _sv
import tracking.views.report_views as _rv
import tracking.views.component_views as _cv
import tracking.views.label_views as _lv
import tracking.views.version_views as _vv
import tracking.views.notification_views as _nv
import tracking.views.watcher_views as _ww
import tracking.views.bulk_views as _bv
import tracking.views.saved_filter_views as _sfv
import tracking.views.user_views as _uv

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard', permanent=False), name='dashboard'),
    path('dashboard', _pv.dashboard, name='dashboard'),
    path('reports', _rv.reports, name='reports'),
    path('releases', _rv.releases, name='releases'),
    # Authentication (Django's built-in login/logout views).
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    # Health check (public, no authentication required).
    path('health/', _pv.health_check, name='health_check'),
	path('projects/', _pv.project_list, name='project_list'),
	path('projects/<int:pk>/', _pv.project_detail, name='project_detail'),
	path('projects/<int:pk>/edit/', _pv.project_edit, name='project_edit'),
	path('projects/new/', _pv.project_create, name='project_create'),
    path('tickets/', _tv.ticket_list, name='ticket_list'),
    path('tickets/bulk/', _bv.ticket_bulk_action, name='ticket_bulk_action'),
    path('tickets/new/', _tv.ticket_create, name='ticket_create'),
    path('tickets/<int:pk>/edit/', _tv.ticket_edit, name='ticket_edit'),
    path('tickets/<int:pk>/', _tv.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/worklog/', _tv.ticket_worklog_create, name='ticket_worklog_create'),
    path('tickets/worklog/<int:pk>/delete/', _tv.worklog_delete, name='worklog_delete'),
    path('tickets/<int:pk>/transition/', _tv.ticket_transition, name='ticket_transition'),
	path('tickets/<int:pk>/sprint/', _tv.ticket_sprint_assign, name='ticket_sprint_assign'),
	path('tickets/order/', _tv.update_backlog_order, name='update_backlog_order'),
    path('tickets/<str:project_key>/', _tv.ticket_list, name='ticket_list_project'),
    path('tickets/<int:project_pk>/tickets/<int:pk>/delete/', _tv.ticket_delete, name='ticket_delete'),
    path('tickets/<int:pk>/relations/add/', _tv.ticket_relation_add, name='ticket_relation_add'),
    path('tickets/relations/<int:pk>/delete/', _tv.ticket_relation_delete, name='ticket_relation_delete'),
	path('tickets/<int:pk>/comment/', _tv.ticket_comment_create, name='ticket_comment_create'),
    path('tickets/comment/<int:pk>/edit/', _tv.ticket_comment_edit, name='ticket_comment_edit'),
    path('tickets/comment/<int:pk>/delete/', _tv.ticket_comment_delete, name='ticket_comment_delete'),
    path('tickets/<int:pk>/attach/', _tv.ticket_attachment_upload, name='ticket_attachment_upload'),
    path('tickets/<int:pk>/media/<int:attachment_pk>/', _tv.ticket_attachment_serve, name='ticket_attachment_serve'),
    path('tickets/attachments/<int:pk>/delete/', _tv.ticket_attachment_delete, name='ticket_attachment_delete'),
    # Saved filters.
    path('saved-filters/create/', _sfv.saved_filter_create, name='saved_filter_create'),
    path('saved-filters/<int:pk>/delete/', _sfv.saved_filter_delete, name='saved_filter_delete'),
    path('saved-filters/<int:pk>/apply/', _sfv.saved_filter_apply, name='saved_filter_apply'),
    # User profiles.
    path('users/<int:pk>/', _uv.user_profile, name='user_profile'),
    path('users/<int:pk>/avatar/', _uv.user_avatar_update, name='user_avatar_update'),
    path('users/<int:pk>/avatar/delete/', _uv.user_avatar_delete, name='user_avatar_delete'),
    # Notifications.
    path('notifications/', _nv.notification_feed, name='notification_feed'),
    path('notifications/mark-read/', _nv.notification_mark_read, name='notification_mark_read'),
    path('notifications/api/', _nv.notification_list_api, name='notification_list_api'),
    # Watchers.
    path('tickets/<int:pk>/watchers/', _ww.watcher_manage, name='ticket_watchers'),
    path('tickets/<int:ticket_pk>/watchers/<int:user_pk>/remove/', _ww.watcher_remove, name='watcher_remove'),
    # Label management (per-project).
    path('projects/<int:pk>/labels/', _lv.label_list, name='label_list'),
    path('labels/', _lv.label_list, name='label_list_all'),
    path('projects/<int:pk>/labels/new/', _lv.label_create, name='label_create'),
    path('labels/<int:pk>/edit/', _lv.label_update, name='label_update'),
    path('labels/<int:pk>/delete/', _lv.label_delete, name='label_delete'),
    # Component management (per-project).
    path('projects/<int:pk>/components/', _cv.component_list, name='component_list'),
	path('components/', _cv.component_list, name='component_list_all'),
    path('projects/<int:pk>/components/new/', _cv.component_create, name='component_create'),
    path('projects/<int:pk>/sprints/new/', _sv.sprint_create, name='sprint_create'),
	path('projects/<int:project_pk>/sprints/<int:sprint_pk>/edit/', _sv.sprint_edit, name='sprint_edit'),
	path('projects/<int:project_pk>/sprints/<int:sprint_pk>/close/', _sv.sprint_close, name='sprint_close'),
	path('projects/<int:project_pk>/velocity/', _sv.sprint_velocity, name='sprint_velocity'),
    path('components/<int:pk>/edit/', _cv.component_update, name='component_update'),
    path('components/<int:pk>/delete/', _cv.component_delete, name='component_delete'),
    # Version / release management.
    path('projects/<int:project_pk>/versions/new/', _vv.version_create, name='version_create'),
    path('projects/<int:project_pk>/roadmap/', _vv.version_roadmap, name='version_roadmap'),
    path('versions/<int:pk>/edit/', _vv.version_edit, name='version_edit'),
    path('versions/<int:pk>/delete/', _vv.version_delete, name='version_delete'),
    path('versions/<int:pk>/release_notes/', _vv.release_notes, name='release_notes'),
]

# JSON REST API for MCP integration (see tracking/api/_common.py).
urlpatterns += [
    path('api/', include('tracking.api.urls')),
]
