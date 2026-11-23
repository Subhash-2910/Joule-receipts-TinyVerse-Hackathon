PY ?= python3

.PHONY: help dashboard test status cloud sync collect experiments evidence report docker-cloud clean

help:
	@echo "make dashboard    Streamlit dashboard on http://localhost:8501"
	@echo "make test         run all tests (offline, no packages needed)"
	@echo "make status       what sensors / SLM / queue are available now"
	@echo "make cloud        run the cloud sync server locally on :8787"
	@echo "make sync         watch the outbox and sync when the server is reachable"
	@echo "make collect      collect 5 minutes of readings (best sensor)"
	@echo "make experiments  idle + batching A/B experiments with receipts (best sensor)"
	@echo "make evidence     same, on the simulated sensor (reproducible anywhere)"
	@echo "make report       write a Markdown report to data/reports/"
	@echo "make docker-cloud build + start the Docker cloud server"

dashboard:
	.venv/bin/streamlit run joule/dashboard.py

test:
	$(PY) -m unittest discover -s tests -t . -v

status:
	$(PY) -m joule status

cloud:
	$(PY) -m joule cloud --port 8787

sync:
	$(PY) -m joule sync --watch

collect:
	$(PY) -m joule collect --seconds 300

experiments:
	$(PY) -m joule experiment idle --repeats 5
	$(PY) -m joule experiment batching --repeats 5

evidence:
	$(PY) -m joule experiment idle --source simulated --repeats 5
	$(PY) -m joule experiment batching --source simulated --repeats 5

report:
	$(PY) -m joule report

docker-cloud:
	docker compose up -d --build cloud

clean:
	rm -rf data/*.db data/*.db-wal data/*.db-shm data/reports cloud-data
