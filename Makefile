src-paths = brute server

.PHONY: all
all: black flake8 isort mypy

.PHONY: mypy
mypy:
	mypy $(src-paths)

.PHONY: isort
isort:
	isort $(src-paths)

.PHONY: flake8
flake8:
	flake8 $(src-paths)

.PHONY: black
black:
	black $(src-paths)

.PHONY: sync-requirements
sync-requirements: compile-requirements compile-requirements-dev
	pip-sync requirements.txt requirements-dev.txt

.PHONY: compile-requirements
compile-requirements:
	pip-compile requirements.in

.PHONY: compile-requirements-dev
compile-requirements-dev:
	pip-compile requirements-dev.in

.PHONY: serve
serve:
	python -m server --port 5000 --credential admin:password

.PHONY: brute
brute:
	python -m brute http://127.0.0.1:5000/ inputs/usernames.txt inputs/passwords.txt
