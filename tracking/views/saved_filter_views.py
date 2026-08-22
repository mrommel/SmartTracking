from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from tracking.models import SavedFilter, Project
import urllib.parse

@login_required
def saved_filter_create(request):
	if request.method == 'POST':
		name = request.POST.get('title')
		filters_json = request.POST.get('filters_json')
		project_id = request.POST.get('project_id')
		project_key = request.POST.get('project')
		if not project_id and not project_key:
			messages.warning(request, 'Project must be specified')
		elif not name:
			messages.warning(request, 'Filter name is required')
		elif project_id:
			project = get_object_or_404(Project, pk=project_id)
			SavedFilter.objects.get_or_create(
				title=name, user=request.user, project=project,
				defaults={'filters_json': filters_json}
			)
			messages.success(request, 'Filter saved')
		elif project_key:
			try:
				project = Project.objects.get(key=project_key)
				# Capture current query params as filters_json if not provided
				if not filters_json:
					filters_json = dict(request.GET)
					# Fallback: try to retrieve from session (saved by ticket_list view)
					if not filters_json and 'last_ticket_list_query' in request.session:
						filters_json = dict(request.session['last_ticket_list_query'])
					# Fallback: try to parse query string from referer header
					if not filters_json:
						referer = request.META.get('HTTP_REFERER', '')
						if referer:
							from urllib.parse import urlparse, parse_qs
							parsed = urlparse(referer)
							parsed_qs = parse_qs(parsed.query)
							filters_json = {k: v if len(v) > 1 else v[0] for k, v in parsed_qs.items()}
							filters_json.pop('page', None)
				SavedFilter.objects.get_or_create(
					title=name, user=request.user, project=project,
					defaults={'filters_json': filters_json}
				)
				messages.success(request, 'Filter saved')
			except Project.DoesNotExist:
				messages.warning(request, 'Project not found')
	else:
		messages.warning(request, 'Project must be specified')
	return redirect('ticket_list')

@login_required
def saved_filter_delete(request, pk):
	filter_obj = get_object_or_404(SavedFilter, pk=pk, user=request.user)
	filter_obj.delete()
	messages.success(request, 'Filter deleted.')
	return redirect('ticket_list')

@login_required
def saved_filter_apply(request, pk):
	try:
		filter_obj = SavedFilter.objects.get(pk=pk, user=request.user)
	except SavedFilter.DoesNotExist:
		messages.warning(request, 'You can only apply your own filters.')
		return redirect('ticket_list')
	filters = filter_obj.filters_json or {}
	base_url = reverse('ticket_list')
	if filters:
		query_string = urllib.parse.urlencode(filters, doseq=True)
		return redirect(f'{base_url}?{query_string}')
	return redirect(base_url)
