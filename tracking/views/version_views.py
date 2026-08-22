from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Version, Project, Ticket
from tracking.forms import VersionForm

@login_required
def version_create(request, pk):
	project = get_object_or_404(Project, pk=pk)
	if request.method == 'POST':
		form = VersionForm(request.POST, project=project)
		if form.is_valid():
			form.save()
			return redirect('project_detail', pk=pk)
	else:
		form = VersionForm(project=project)
	return render(request, 'tracking/version_create.html', {'form': form, 'project': project})

@login_required
def version_edit(request, pk):
	version = get_object_or_404(Version, pk=pk)
	if request.method == 'POST':
		form = VersionForm(request.POST, instance=version)
		if form.is_valid():
			form.save()
			return redirect('release_notes', pk=version.pk)
	else:
		form = VersionForm(instance=version)
	return render(request, 'tracking/version_edit.html', {'form': form, 'version': version})

@login_required
def version_delete(request, pk):
	version = get_object_or_404(Version, pk=pk)
	version.delete()
	return redirect('releases')

@login_required
def version_roadmap(request, project_pk):
	project = get_object_or_404(Project, pk=project_pk)
	versions = project.versions.all().order_by('name')
	return render(request, 'tracking/version_roadmap.html', {'versions': versions})

@login_required
def release_notes(request, pk):
	version = get_object_or_404(Version, pk=pk)
	tickets = version.tickets.all()
	return render(request, 'tracking/release_notes.html', {'version': version, 'tickets': tickets})
