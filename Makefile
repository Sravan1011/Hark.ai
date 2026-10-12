VENV := .venv
BIN  := $(VENV)/bin

.PHONY: install setup-system ollama doctor test lint

install:            ## create .venv and install Hark with all extras
	bash scripts/setup-linux.sh --python-only

setup-system:       ## system packages + input/uinput permissions (uses sudo)
	bash scripts/setup-linux.sh --system-only

ollama:             ## optional: install Ollama and pull the default cleanup model
	bash scripts/install-ollama.sh

doctor:
	$(BIN)/hark doctor

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check src tests
