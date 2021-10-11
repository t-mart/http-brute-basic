.PHONY: all
all: black flake8 isort mypy

.PHONY: mypy
mypy:
	mypy brute server

.PHONY: isort
isort:
	isort brute server

.PHONY: flake8
flake8:
	flake8 brute server

.PHONY: black
black:
	black brute server

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
