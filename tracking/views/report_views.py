from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from tracking.models import Sprint, Project, Version
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

@login_required
@cache_page(settings.DASHBOARD_CACHE_TIMEOUT)
def sprint_velocity(request, project_pk):
	project = get_object_or_404(Project, pk=project_pk)
	sprints = project.sprints.filter(is_backlog=False).order_by('-end_date')[:10]
	return render(request, 'tracking/sprint_velocity.html', {
		'sprints': sprints,
		'project': project
	})

@login_required
@cache_page(settings.DASHBOARD_CACHE_TIMEOUT)
def reports(request):
	return render(request, 'tracking/reports.html')

@login_required
@cache_page(settings.DASHBOARD_CACHE_TIMEOUT)
def releases(request):
	versions = Version.objects.all().order_by('-created_at')
	return render(request, 'tracking/releases.html', {'versions': versions})
