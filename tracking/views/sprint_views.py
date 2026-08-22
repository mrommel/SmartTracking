from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Sprint, Comment, Attachment, Project
from tracking.forms import SprintForm, SprintCloseForm, CommentForm, AttachmentForm
from django.contrib import messages
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

@login_required
def sprint_create(request, pk):
	project = get_object_or_404(Project, pk=pk)
	if request.method == 'POST':
		form = SprintForm(request.POST, project=project)
		if form.is_valid():
			sprint = form.save()
			messages.success(request, _("Sprint '%(name)s' created.") % {'name': sprint.name})
			return redirect('project_detail', pk=pk)
	else:
		form = SprintForm(project=project)
	return render(request, 'tracking/sprint_create.html', {'form': form, 'project': project})

@login_required
def sprint_edit(request, project_pk, sprint_pk):
	sprint = get_object_or_404(Sprint, pk=sprint_pk, project_id=project_pk)
	if request.method == 'POST':
		form = SprintForm(request.POST, instance=sprint)
		if form.is_valid():
			form.save()
			return redirect('project_detail', pk=project_pk)
	else:
		form = SprintForm(instance=sprint)
	return render(request, 'tracking/sprint_edit.html', {'form': form, 'sprint': sprint, 'project': sprint.project})

@login_required
def sprint_close(request, project_pk, sprint_pk):
	sprint = get_object_or_404(Sprint, pk=sprint_pk, project_id=project_pk)
	if request.method == 'POST':
		form = SprintCloseForm(request.POST, project=project, exclude_sprint=sprint)
		if form.is_valid():
			action = form.cleaned_data['action']
			target_id = form.cleaned_data['target_sprint'].pk if form.cleaned_data['target_sprint'] else None
			sprint.close_with_action(action, target_id)
			messages.success(request, _("Sprint '%(name)s' closed.") % {'name': sprint.name})
			return redirect('project_detail', pk=project_pk)
	else:
		form = SprintCloseForm(project=project, exclude_sprint=sprint)
	return render(request, 'tracking/sprint_close.html', {'form': form, 'sprint': sprint, 'project': project})

@login_required
def sprint_velocity(request, project_pk):
	from tracking.models import Project
	project = get_object_or_404(Project, pk=project_pk)
	sprints = project.sprints.filter(is_backlog=False).order_by('-end_date')[:10]
	return render(request, 'tracking/sprint_velocity.html', {'sprints': sprints, 'project': project})
