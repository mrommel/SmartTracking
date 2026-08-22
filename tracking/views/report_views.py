from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from tracking.models import Sprint, Project, Version
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

@login_required
def sprint_velocity(request, project_pk):
	project = get_object_or_404(Project, pk=project_pk)
	sprints = project.sprints.filter(is_backlog=False).order_by('-end_date')[:10]
	return render(request, 'tracking/sprint_velocity.html', {
		'sprints': sprints,
		'project': project
	})

@login_required
def reports(request):
	return render(request, 'tracking/reports.html')

@login_required
def releases(request):
	versions = Version.objects.all().order_by('-created_at')
	return render(request, 'tracking/releases.html', {'versions': versions})
