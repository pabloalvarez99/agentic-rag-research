PYTHON ?= python
QUESTION ?= What does hybrid retrieval buy over dense retrieval alone?

.PHONY: test lint run research-fake

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

run:
	$(PYTHON) -m uvicorn agentic_rag.main:app --host 127.0.0.1 --port 8010

research-fake:
	$(PYTHON) -m agentic_rag.research --question "$(QUESTION)" --retriever fake
