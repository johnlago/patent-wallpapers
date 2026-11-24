.PHONY: all fetch build trmnl plugin plugin-lint plugin-test plugin-contact plugin-serve
all: fetch build
fetch:
	python3 src/fetch.py
build:
	python3 src/build.py
	python3 src/trmnl.py
	python3 src/plugin.py
trmnl:
	python3 src/trmnl.py
plugin:
	python3 src/plugin.py

# The native TRMNL plugin (trmnl-plugin/) is checked with trmnlp in Docker. The repo root is
# mounted, so the plugin's tests and previews can read output/plugin/.
TRMNLP = docker run --rm --init -v "$(CURDIR):/plugin"
plugin-lint:
	$(TRMNLP) trmnl/trmnlp lint -d /plugin/trmnl-plugin
plugin-test:
	$(TRMNLP) trmnl/trmnlp test -d /plugin/trmnl-plugin
# Renders every patent in every layout on the original TRMNL (4 grays) and makes
# output/plugin-preview/contact-<layout>.png for review.
plugin-contact:
	rm -rf output/plugin-preview
	$(TRMNLP) -e CONTACT_DIR=/plugin/output/plugin-preview trmnl/trmnlp test -d /plugin/trmnl-plugin
	python3 src/plugin.py contact
# Live preview at http://localhost:4567. It polls the published manifest on GitHub Pages.
plugin-serve:
	$(TRMNLP) -p 4567:4567 trmnl/trmnlp serve -d /plugin/trmnl-plugin
