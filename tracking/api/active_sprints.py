from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Sprint, Project, Ticket
from django.db.models import Prefetch

@api.require_http_methods(['GET'])
def active_sprint(request, key):
	project = get_object_or_404(Project, key=key)
	active_sprint = project.sprints.filter(is_active=True).first()
	if active_sprint:
		tickets = Ticket.objects.filter(sprint=active_sprint).select_related('project', 'assignee', 'sprint', 'parent_epic').prefetch_related('labels', 'components')
		results = [ticket._data() for ticket in tickets]
		return JsonResponse({
			'sprint': active_sprint._data(),
			'count': len(results),
			'pagination': {'next': None, 'previous': None},
			'results': results,
		})
	return JsonResponse({'sprint': None, 'count': 0, 'pagination': {'next': None, 'previous': None}, 'results': []})
