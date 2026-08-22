from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from . import _common as api
from tracking.models import Ticket

@api.require_http_methods(['GET'])
@api.require_api_auth
def meta(request):
	states = {s.value: s.name for s in Ticket.State}
	priorities = {p.value: p.name for p in Ticket.Priority}
	types = {t.value: t.name for t in Ticket.Type}
	transitions = Ticket.TRANSITIONS
	return JsonResponse({
		'states': states,
		'priorities': priorities,
		'types': types,
		'relation_types': [r.value for r in Ticket.RelationType],
		'transitions': {s.value: [t.value for t in ts] for s, ts in transitions.items()},
		'worklog_enabled': True,
	})
