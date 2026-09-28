.PHONY: test test-backend dev-backend dev-frontend dev-sim up down build sim-spike aws-setup

PYTHON ?= python
NPM ?= npm

test:
	cd backend && $(PYTHON) -m pytest -v

# Backend and simulator must agree on the log file (the sim control file lives next to it).
LOG_FILE ?= ../data/app.log

dev-backend:
	cd backend && LOG_FILE_PATH=$(LOG_FILE) $(PYTHON) -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && $(NPM) run dev

dev-sim:
	cd backend && $(PYTHON) -m simulator.generate_logs --file $(LOG_FILE) --rps 30 --base-error 0.02

build:
	cd frontend && $(NPM) run build

up:
	docker compose up --build -d

down:
	docker compose down

sim-spike:
	curl -X POST http://localhost:8000/api/sim/spike \
		-H "Content-Type: application/json" \
		-d '{"duration_sec": 60, "error_ratio": 0.35, "scenario": "$(or $(SCENARIO),spike)"}'

aws-setup:
	bash infra/aws-setup.sh
