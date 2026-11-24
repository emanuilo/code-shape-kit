# The kit's own tasks. Projects use code_shape/templates/code-shape.mk instead.
.PHONY: install test self-check self-report other-report

install:        ## Install the kit, the tools it drives, and pytest
	pip install -e ".[tools,dev]"

test:           ## Prove the gates fail when they should (uses examples/tidy_app)
	pytest -q

self-check:     ## The kit must pass its own gates with an empty baseline
	code-shape check

self-report:
	code-shape report --out /tmp/code-shape-self-report.md

# Read-only report on another project, e.g.  make other-report ROOT=../myapp CONFIG=myapp.shape.toml
# (CONFIG is optional; without it the project's own pyproject.toml is used.)
OUT ?= code-shape-report.md
other-report:
	code-shape report --root $(ROOT) $(if $(CONFIG),--config $(CONFIG)) --out $(OUT) --trend 6
