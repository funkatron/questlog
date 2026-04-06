SWIFTC=xcrun --sdk macosx swiftc
BIN=bin

all: build

build: $(BIN)/frontapp $(BIN)/ocrshot

$(BIN)/frontapp: src/frontapp.swift
	mkdir -p $(BIN)
	$(SWIFTC) -O -framework AppKit -framework ApplicationServices -framework Foundation $< -o $@

$(BIN)/ocrshot: src/ocrshot.swift
	mkdir -p $(BIN)
	$(SWIFTC) -O -framework AppKit -framework Vision -framework CoreGraphics -framework Foundation $< -o $@

clean:
	rm -rf $(BIN)/*

.PHONY: test install
test:
	@if command -v uv >/dev/null 2>&1; then \
		uv run pytest -q; \
	else \
		pytest -q; \
	fi

install:
	@if command -v uv >/dev/null 2>&1; then \
		echo "Installing with uv..."; \
		uv sync --all-extras; \
	else \
		echo "uv not found, using pip..."; \
		pip install -e ".[all]"; \
	fi
	@echo "Initializing database..."; \
	if command -v uv >/dev/null 2>&1; then \
		uv run questlog init-db; \
	else \
		python -m questlog init-db; \
	fi
	@echo "Installation complete! Edit config.yaml as needed."
