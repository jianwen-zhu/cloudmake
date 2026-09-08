# Maintainer-facing operations for the local backend. The supported launcher
# path invokes project Make directly in bin/cloudmake rather than entering here.

.PHONY: help start status stop sync collect dispatch fetch shell open environment

help:
	@echo 'The local backend invokes the selected project Makefile directly.'
	@echo 'Use the cloudmake launcher for project-target execution.'

start: doctor
	@echo '[local] No compute environment needs to be started.'

status: doctor
	@echo '[local] Project Makefile is available at $(PROJECT_DIR)/$(PROJECT_MAKEFILE).'

environment: prerequisites
	@profile='$(CLOUDMAKE_STATE_ROOT)/local/environment-profile.json'; \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/vm_capabilities.py' \
			--workspace '$(PROJECT_DIR)' --result "$$profile" >/dev/null; \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/vm_capabilities.py' --render "$$profile"

stop: prerequisites
	@echo '[local] No compute environment needs to be stopped.'

sync: doctor
	@echo '[local] The working tree is already local; nothing to synchronize.'

dispatch collect:
	@echo '[local] Project targets are dispatched directly by the cloudmake launcher.' >&2
	@exit 2

fetch:
	@echo '[local] Output is already local; use --collect DIR TARGET to materialize artifacts/.' >&2
	@exit 2

shell:
	@echo '[local] No separate backend shell exists; use a shell in the project directory.' >&2
	@exit 2

open:
	@echo '[local] No provider interface exists for the local backend.' >&2
	@exit 2
