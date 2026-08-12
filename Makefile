# define the name of the virtual environment directory
VENV := .venv

# default target, when make executed without arguments
all: venv

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	./$(VENV)/bin/python3.12 -m pip install --upgrade pip
	./$(VENV)/bin/pip3.12 install -r requirements.txt

# venv is a shortcut target
venv: $(VENV)/bin/activate

run: venv
	# Load .env in the same subshell as runserver. POSIX `.` works on macOS /bin/sh
	# (bash-only `source` does not). `set -a` auto-exports every variable defined
	# while sourcing; `[ -f .env ]` keeps a missing .env silently ok.
	# Start the MCP server (streamable HTTP, port 8091) in the background, then the
	# Django dev server in the foreground. The trap stops the MCP server on exit.
	set -a; [ -f .env ] && . ./.env && set +a; \
	./$(VENV)/bin/python3.12 mcp_server.py & \
	MCP_PID=$$!; \
	trap "kill $$MCP_PID 2>/dev/null" EXIT INT TERM; \
	./$(VENV)/bin/python3.12 manage.py runserver 8092

clean:
	rm -rf $(VENV)
	find . -type f -name '*.pyc' -delete

makemigrations: venv
	./$(VENV)/bin/python3.12 manage.py makemigrations
	./$(VENV)/bin/python3.12 manage.py sqlmigrate tracking 0001  # change this
	./$(VENV)/bin/python3.12 manage.py migrate

migrate: venv
	./$(VENV)/bin/python3.12 manage.py migrate

# translations

preparetranslations: venv
	./$(VENV)/bin/python3.12 manage.py makemessages -l de -l en -e html,txt,py --ignore=venv/*

compiletranslations: venv
	./$(VENV)/bin/python3.12 manage.py compilemessages --ignore=venv/*

# createsuperuser: venv
#	./$(VENV)/bin/python3.12 manage.py createsuperuser
# mrommel + mKuAZ6v4ytxLPO37

# createapp: venv
#	./$(VENV)/bin/python3.12 manage.py startapp tracking

# testing

test: venv
	./$(VENV)/bin/python3.12 manage.py test tracking