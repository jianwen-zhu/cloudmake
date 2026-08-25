# Shared local readiness checks. Backends declare requirements; transports make
# operational targets depend on `prerequisites`. `doctor` adds a read-only
# provider authentication/access probe and must never allocate compute.

BACKEND_REQUIRED_COMMANDS ?=
BACKEND_REQUIRED_VARIABLES ?=
BACKEND_INSTALL_HINT ?= See the backend prerequisites in README.md.
BACKEND_REQUIRES_PYTHON ?= no
BACKEND_VALIDATE ?= :
BACKEND_DOCTOR_PROBE ?= :
PYTHON_BIN ?= python3
PYTHON_MINIMUM ?= 3.9

.PHONY: prerequisites doctor

prerequisites: backend-contract
	@missing=0; \
	for command in $(BACKEND_REQUIRED_COMMANDS); do \
		if ! command -v "$$command" >/dev/null 2>&1; then \
			echo "Missing required command: $$command" >&2; \
			missing=1; \
		fi; \
	done; \
	if test "$$missing" -ne 0; then \
		printf '%s\n' '$(BACKEND_INSTALL_HINT)' >&2; \
		echo 'See README.md: Backend prerequisites.' >&2; \
		exit 2; \
	fi
	@missing=0; \
	$(foreach variable,$(BACKEND_REQUIRED_VARIABLES),\
		if test -z "$($(variable))"; then \
			echo 'Missing required setting: $(variable)' >&2; \
			missing=1; \
		fi; ) \
	if test "$$missing" -ne 0; then \
		printf '%s\n' '$(BACKEND_INSTALL_HINT)' >&2; \
		echo 'See README.md: Backend prerequisites.' >&2; \
		exit 2; \
	fi
	@if test '$(BACKEND_REQUIRES_PYTHON)' = yes; then \
		'$(PYTHON_BIN)' -c 'import sys; minimum=tuple(map(int,"$(PYTHON_MINIMUM)".split("."))); raise SystemExit(sys.version_info[:2] < minimum)' || { \
			echo 'Python $(PYTHON_MINIMUM) or newer is required by backend $(BACKEND).' >&2; \
			exit 2; \
		}; \
	fi
	@$(BACKEND_VALIDATE)

doctor: prerequisites
	@echo '[doctor] Probing backend $(BACKEND) without allocating compute...'
	@if ! { $(BACKEND_DOCTOR_PROBE); }; then \
		echo '[doctor] Backend $(BACKEND) is installed but its authentication or access probe failed.' >&2; \
		printf '%s\n' '$(BACKEND_INSTALL_HINT)' >&2; \
		exit 2; \
	fi
	@echo '[doctor] Backend $(BACKEND) is ready.'
