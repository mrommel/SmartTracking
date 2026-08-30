# define the name of the virtual environment directory
VENV := .venv
MIGRATION ?= 0001

# default target, when make executed without arguments
all: venv

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	./$(VENV)/bin/python3.12 -m pip install --upgrade pip
	./$(VENV)/bin/pip3.12 install -r requirements.txt

# venv is a shortcut target
venv: $(VENV)/bin/activate

MCP_PORT ?= 8091

run: venv
	# Load .env in the same subshell as runserver. POSIX `.` works on macOS /bin/sh
	# (bash-only `source` does not). `set -a` auto-exports every variable defined
	# while sourcing; `[ -f .env ]` keeps a missing .env silently ok.
	# Start the MCP server (streamable HTTP, port 8091) in the background, then the
	# Django dev server in the foreground. The trap stops the MCP server on exit.
	# The MCP server is supervised: if it dies (bad request, OOM, upstream blip) it
	# is restarted after 1 s instead of leaving the editor with a dead endpoint.
	set -a; [ -f .env ] && . ./.env && set +a; \
	( while true; do ./$(VENV)/bin/python3.12 mcp_server.py || true; \
	    echo "[make run] MCP server exited - restarting in 1s"; sleep 1; done ) & \
	MCP_PID=$$!; \
	trap "kill $$MCP_PID 2>/dev/null" EXIT INT TERM; \
	./$(VENV)/bin/python3.12 manage.py runserver 8092

## Serve MCP over stdio (for clients that spawn the server as a subprocess).
## No port, no session ids - the most robust transport for editor agents.
mcp-stdio: venv
	@set -a; [ -f .env ] && . ./.env && set +a; \
	exec ./$(VENV)/bin/python3.12 mcp_server.py --stdio

## Probe the running MCP server (and the Django API behind it).
## Exits non-zero when either is down, so consuming projects can gate on it.
mcp-health:
	@curl -fsS http://127.0.0.1:$(MCP_PORT)/health \
	  && echo "" \
	  || (echo "MCP server not healthy on port $(MCP_PORT) - run 'make run'"; exit 1)

.PHONY: run mcp-stdio mcp-health

clean:
	rm -rf $(VENV)
	find . -type f -name '*.pyc' -delete

makemigrations: venv
	./$(VENV)/bin/python3.12 manage.py makemigrations
	./$(VENV)/bin/python3.12 manage.py sqlmigrate tracking $(MIGRATION)  # override: make makemigrations MIGRATION=0015
	./$(VENV)/bin/python3.12 manage.py migrate

migrate: venv
	./$(VENV)/bin/python3.12 manage.py migrate

# backup

# Zip the SQLite DB into backups/yyyy-mm-dd db.sqlite3.zip.
# Override retention: make backup KEEP=30 (0 = keep everything)
KEEP ?= 0

backup: venv
	./$(VENV)/bin/python3.12 manage.py backup_db --keep $(KEEP)

.PHONY: backup

# translations

preparetranslations: venv
	./$(VENV)/bin/python3.12 manage.py makemessages -l de -l en -e html,txt,py --ignore=venv/*

compiletranslations: venv
	./$(VENV)/bin/python3.12 manage.py compilemessages --ignore=venv/*

check-translations: venv
	./$(VENV)/bin/python3.12 scripts/check_translations.py

# createsuperuser: venv
#	./$(VENV)/bin/python3.12 manage.py createsuperuser
# mrommel + mKuAZ6v4ytxLPO37

# createapp: venv
#	./$(VENV)/bin/python3.12 manage.py startapp tracking

# testing

test: venv
	./$(VENV)/bin/python3.12 -m coverage run --source=tracking manage.py test tracking
	./$(VENV)/bin/python3.12 -m coverage report

coverage-report: venv
	./$(VENV)/bin/python3.12 -m coverage html --fail-under=0
	@echo "HTML report generated at htmlcov/index.html"

coverage-clean: venv
	./$(VENV)/bin/python3.12 -m coverage erase