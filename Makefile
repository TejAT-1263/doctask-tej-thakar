# doctask-tej-thakar — development convenience targets
#
# Quick start (no Docker):
#   make test    — install deps into user space, then run all 39 tests
#   make dev     — start FastAPI on :8000
#   make mcp     — start MCP stdio server
#
# Docker:
#   make up      — docker-compose up --build
#   make down    — docker-compose down
#
# pip install flags:
# - Inside a virtualenv (VIRTUAL_ENV is set): plain install, no --user
# - Outside a virtualenv: --user to avoid needing admin rights on macOS/Linux

PYTHON  := python3
PIP     := $(PYTHON) -m pip
PYTEST  := $(PYTHON) -m pytest
BACKEND := backend

PIP_FLAGS := $(if $(VIRTUAL_ENV),,--user)

.PHONY: setup
setup:
	$(PIP) install $(PIP_FLAGS) -r $(BACKEND)/requirements.txt

.PHONY: test
test: setup
	$(PYTEST) $(BACKEND)/tests/ -q

.PHONY: test-v
test-v: setup
	$(PYTEST) $(BACKEND)/tests/ -v

.PHONY: dev
dev: setup
	cd $(BACKEND) && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: mcp
mcp: setup
	cd $(BACKEND) && $(PYTHON) -m mcp_server.server

.PHONY: up
up:
	docker-compose up --build

.PHONY: down
down:
	docker-compose down

.PHONY: clean
clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f $(BACKEND)/test*.db $(BACKEND)/test*.db-journal
	rm -f /tmp/doctask_test*.db
