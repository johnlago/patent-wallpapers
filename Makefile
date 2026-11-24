.PHONY: all fetch build trmnl
all: fetch build
fetch:
	python3 src/fetch.py
build:
	python3 src/build.py
	python3 src/trmnl.py
trmnl:
	python3 src/trmnl.py
