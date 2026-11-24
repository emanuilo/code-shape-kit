# Include from your project's Makefile:   include tools/code-shape-kit/templates/code-shape.mk
# Then:  make shape-report | shape-check | shape-baseline | shape-tighten
#        make shape-check BASE=origin/main   (also lists the rules loosened since BASE)

SHAPE ?= code-shape
SHAPE_ARGS ?=
BASE ?=

.PHONY: shape-report shape-check shape-baseline shape-tighten

shape-report:     ## Run everything, write code-shape-report.md (never fails)
	$(SHAPE) report --trend 8 $(SHAPE_ARGS)

shape-check:      ## CI gate: fail on new or worse violations
	$(SHAPE) check $(if $(BASE),--base $(BASE)) $(SHAPE_ARGS)

shape-baseline:   ## Record today's violations (existing projects, once; review the diff!)
	$(SHAPE) baseline $(SHAPE_ARGS)

shape-tighten:    ## Lock in improvements (only ever shrinks the baseline)
	$(SHAPE) tighten $(SHAPE_ARGS)
