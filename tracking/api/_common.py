from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed, HttpResponseForbidden, HttpRequest, HttpResponseServerError
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils import crypto
from django.conf import settings
from django.db.models import Field
from typing import Any, Optional, Union
import json
import urllib.parse

# --- API Core Helpers ---

def parse_json(request: HttpRequest, key: str = None) -> dict:
	"""Safely parse request.body as JSON, returning {} on failure."""
	body = request.body
	if not body:
		return {}
	try:
		data = json.loads(body)
		return data.get(key) if key else data
	except (json.JSONDecodeError, ValueError):
		return {}


def get_object_or_404_json(model, *args, **kwargs) -> Any:
	"""Retrieve a model instance or return a 404 JSON response."""
	try:
		return get_object_or_404(model, *args, **kwargs)
	except Exception:
		return JsonResponse({'error': 'Not found'}, status=404)


def _page_json(request: HttpRequest, qs, default_page_size: int = 25) -> JsonResponse:
	page_size = request.GET.get('page_size', default_page_size)
	try:
		page_size = int(page_size)
	except (ValueError, TypeError):
		page_size = default_page_size
	page_size = min(page_size, 100)
	page = request.GET.get('page', 1)
	try:
		page = int(page)
	except (ValueError, TypeError):
		page = 1
	if page < 1: page = 1

	# Preserve non-page query params for next/prev URLs
	qs_dict = urllib.parse.parse_qs(request.META.get('QUERY_STRING', ''))
	qs_dict['page'] = [str(page)]
	current_params = urllib.parse.urlencode(qs_dict, doseq=True)

	count = qs.count()
	start = (page - 1) * page_size
	end = start + page_size
	page_results = qs[start:end]

	next_url = None
	previous_url = None
	if end < count:
		next_qs = qs_dict.copy()
		next_qs['page'] = [str(page + 1)]
		next_url = f"{request.path}?{urllib.parse.urlencode(next_qs, doseq=True)}" if next_qs.get('page') else next_url
	if page > 1:
		prev_qs = qs_dict.copy()
		prev_qs['page'] = [str(page - 1)]
		previous_url = f"{request.path}?{urllib.parse.urlencode(prev_qs, doseq=True)}"

	return JsonResponse({
		'count': count,
		'pagination': {
			'next': next_url,
			'previous': previous_url
		},
		'results': _serialize_list(page_results)
	})

def _serialize_list(objs):
	return [_serialize(obj) for obj in objs]

def _serialize(obj):
	if hasattr(obj, '_data'):
		data = obj._data()
	else:
		data = {f.name: getattr(obj, f.name) for f in obj._meta.get_fields() if isinstance(f, Field) and hasattr(obj, f.name)}
	return data

def _valid_required(data: dict, fields: list) -> Optional[str]:
	missing = [f for f in fields if f not in data]
	return next(iter(missing), None)

def _valid_optional(data: dict, fields: list) -> list:
	return [f for f in fields if f not in data]

def require_api_auth(view_func):
	def wrapper(request: HttpRequest, *args, **kwargs):
		if request.user.is_authenticated:
			return view_func(request, *args, **kwargs)
		token = request.headers.get('Authorization', '').removeprefix('Bearer ')
		if not token:
			token = request.headers.get('X-API-Token', '')
		api_token = settings.TRACKING_API_TOKEN
		if api_token and token and token == api_token:
			return view_func(request, *args, **kwargs)
		resp = JsonResponse({'error': 'Authentication required'}, status=401)
		resp['WWW-Authenticate'] = 'Bearer'
		return resp
	return wrapper

def require_http_methods(methods: list):
	"""Return a decorator that checks the method, then auth, then CSRF.
	
	The original file stacked them via:  @csrf_exempt → @require_api_auth → @require_http_methods
	We do the same here so Bearer-token auth can bypass CSRF.
	"""
	def decorator(view_func):
		@csrf_exempt
		@require_api_auth
		def wrapper(request: HttpRequest, *args, **kwargs):
			if request.method not in methods:
				return HttpResponseNotAllowed(methods)
			return view_func(request, *args, **kwargs)
		return wrapper
	return decorator
