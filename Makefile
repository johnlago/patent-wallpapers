.PHONY: all fetch build
all: fetch build
fetch:
	python3 src/fetch.py
build:
	python3 src/build.py
