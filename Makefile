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

.PHONY: test
test:
	pytest -q
