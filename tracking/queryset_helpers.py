from django.db.models import Q, Case, When, Value, IntegerField
from tracking.models import Ticket


SORT_MAP = {
	'title': 'title',
	'type': 'type',
	'priority': 'priority',
	'state': 'state',
	'due_date': 'due_date',
	'created': 'created_at',
	'updated': 'updated_at',
}


def build_ticket_queryset(request, project_key: str | None = None,
		labels_by_id: bool = False, components_by_id: bool = False):
	"""Build and return a filtered Ticket queryset from request query params.

	Supported query parameters:

	* ``state`` – one or more state values (multi-select).
	* ``label`` – one or more label **names** (or IDs when ``labels_by_id=True``).
	* ``component`` – one or more component **names** (or IDs when ``components_by_id=True``).
	* ``project`` – project key (single value, can be overridden by
	  the ``project_key`` positional argument).
	* ``assignee`` – ``me``, ``unassigned``, or one or more user PK integers.
	* ``query`` / ``q`` – free-text search across title, description, and ticket PK.
	* ``sort`` – sort field (maps via ``SORT_MAP``; default ``created_at``).
	* ``order`` – ``asc`` or ``desc`` (default ``desc``).

	The ``sort=priority`` path uses a Case/When annotation for custom
	human-readable ordering (CRITICAL first).

	The queryset always uses ``select_related('sprint', 'parent_epic', 'assignee')``
	for FK reads and ``distinct()`` to eliminate duplicate rows from M2M joins.

	:param request: Django ``HttpRequest`` (provides ``request.user`` and ``request.GET``).
	:param project_key: Optional project key to constrain the queryset; bypasses the
	  ``?project=`` query param.
	:param labels_by_id: When True, interpret ``label`` values as integer PKs;
	  otherwise look up labels by name.
	:param components_by_id: When True, interpret ``component`` values as integer PKs;
	  otherwise look up components by name.
	:rtype: QuerySet[Ticket]
	:return: A QuerySet ready for slicing / pagination.
	"""
	qs = Ticket.objects.all().select_related('sprint', 'parent_epic', 'assignee')

	# --- Project filter (positional arg takes precedence over query param) ------

	if project_key:
		qs = qs.filter(project__key=project_key)
	else:
		project_key = request.GET.get('project')
		if project_key:
			qs = qs.filter(project__key=project_key)

	# --- Multi-value filters (state, label, component) -------------------------

	if request.GET.getlist('state'):
		qs = qs.filter(state__in=request.GET.getlist('state'))

	if request.GET.getlist('label'):
		if labels_by_id:
			# Resolve by PK (integer IDs).
			ids = [int(l) for l in request.GET.getlist('label') if l.isdigit()]
			if ids:
				qs = qs.filter(labels__pk__in=ids)
		else:
			# Resolve by name (default, matches HTML filter behaviour).
			for label_name in request.GET.getlist('label'):
				qs = qs.filter(labels__name=label_name)

	if request.GET.getlist('component'):
		if components_by_id:
			# Resolve by PK (integer IDs).
			ids = [int(c) for c in request.GET.getlist('component') if c.isdigit()]
			if ids:
				qs = qs.filter(components__pk__in=ids)
		else:
			# Resolve by name (default, matches HTML filter behaviour).
			for comp_name in request.GET.getlist('component'):
				qs = qs.filter(components__name=comp_name)

	# --- Assignee filter -------------------------------------------------------

	assignee_values = request.GET.getlist('assignee')
	if 'me' in assignee_values:
		qs = qs.filter(assignee=request.user)
	elif 'unassigned' in assignee_values:
		qs = qs.filter(assignee__isnull=True)
	elif assignee_values:
		numeric_ids = [aid for aid in assignee_values if aid.isdigit()]
		if numeric_ids:
			qs = qs.filter(assignee_id__in=numeric_ids)

	# --- Free-text query -------------------------------------------------------

	query = request.GET.get('query') or request.GET.get('q')
	if query:
		if query.isdigit():
			qs = qs.filter(
				Q(title__icontains=query)
				| Q(description__icontains=query)
				| Q(pk=int(query))
			)
		else:
			qs = qs.filter(
				Q(title__icontains=query) | Q(description__icontains=query)
			)

	# --- Sorting ---------------------------------------------------------------

	sort_field = request.GET.get('sort', 'created_at')
	order = request.GET.get('order', 'desc')
	db_field = SORT_MAP.get(sort_field, 'created_at')

	if sort_field == 'priority':
		priority_map = {
			Ticket.Priority.CRITICAL: 0,
			Ticket.Priority.HIGH: 1,
			Ticket.Priority.MEDIUM: 2,
			Ticket.Priority.LOW: 3,
		}
		qs = qs.annotate(
			_priority_sort=Case(
				*[When(priority=p, then=v) for p, v in priority_map.items()],
				default=4,
				output_field=IntegerField(),
			)
		)
		sort_key = '_priority_sort' if order == 'desc' else '-_priority_sort'
		qs = qs.order_by(sort_key)
	else:
		sort_key = f'-{db_field}' if order == 'desc' else db_field
		qs = qs.order_by(sort_key)

	return qs.distinct()
