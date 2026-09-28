.DEFAULT_GOAL := help

.PHONY: help install test web-install web-dev web-build up down logs build-standalone clean

help:
	@echo "RobinCop commands"
	@echo "  make install           Install Python and web dependencies"
	@echo "  make test              Run Python unit tests"
	@echo "  make web-dev           Start the web development server"
	@echo "  make web-build         Build the web application"
	@echo "  make up                Build and start the complete local stack"
	@echo "  make down              Stop the local stack"
	@echo "  make logs              Follow local stack logs"
	@echo "  make build-standalone  Generate run_robinhood_standalone.py"
	@echo "  make clean             Remove caches and generated build output"

install:
	python3 -m pip install -e . -r apps/api/requirements.txt
	npm --prefix apps/web ci

test:
	python3 -m unittest discover -s tests -v

web-install:
	npm --prefix apps/web ci

web-dev:
	npm --prefix apps/web run dev

web-build:
	npm --prefix apps/web run build

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

build-standalone:
	python3 build_standalone.py

clean:
	rm -rf .cache .pytest_cache __pycache__
	rm -rf copybot/__pycache__ tests/__pycache__
	rm -rf apps/api/robincop_api/__pycache__ apps/api/robincop_api/services/__pycache__
	rm -rf apps/api/alembic/__pycache__ apps/api/alembic/versions/__pycache__
	rm -rf apps/web/.next apps/web/.vinext apps/web/.wrangler apps/web/dist

