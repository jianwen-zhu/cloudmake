SHELL := /bin/sh

STATE := .workspace-state
RESULTS := results
PROGRAM := $(STATE)/prefix/bin/hello

.PHONY: provision run advance clean

provision: $(PROGRAM)

$(PROGRAM): hello.c
	@mkdir -p '$(dir $@)'
	@cc -O2 -o '$@' '$<'

run: $(PROGRAM)
	@mkdir -p '$(RESULTS)'
	@'$(PROGRAM)' | tee '$(RESULTS)/hello.txt'

advance:
	@mkdir -p '$(STATE)'
	@count=0; test ! -f '$(STATE)/generation' || count="$$(cat '$(STATE)/generation')"; \
		count=$$((count + 1)); printf '%s\n' "$$count" > '$(STATE)/generation.tmp'; \
		mv '$(STATE)/generation.tmp' '$(STATE)/generation'; \
		printf 'generation:%s\n' "$$count"

clean:
	@rm -rf '$(STATE)' '$(RESULTS)'
