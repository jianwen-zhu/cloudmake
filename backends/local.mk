# The local backend is the reference execution surface. Public project-target
# invocations bypass the backend engine and call the project Makefile directly;
# this descriptor provides consistent diagnostics and lifecycle operations.
BACKEND_TRANSPORT := local
BACKEND_ACCESS_CLASS := local
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := local
BACKEND_CAPABILITIES := sync execute status artifacts

MAKE_BIN ?= make

BACKEND_REQUIRED_COMMANDS := $(MAKE_BIN)
BACKEND_INSTALL_HINT := Install GNU Make or a compatible Make implementation.
BACKEND_VALIDATE := test -f '$(PROJECT_DIR)/$(PROJECT_MAKEFILE)' || { echo 'Project Makefile was not found: $(PROJECT_DIR)/$(PROJECT_MAKEFILE)' >&2; exit 2; }
BACKEND_DOCTOR_PROBE := test -r '$(PROJECT_DIR)/$(PROJECT_MAKEFILE)'
BACKEND_VERSION_COMMAND := $(MAKE_BIN) --version
BACKEND_TESTED_CLIENT := GNU Make 3.81 or newer
BACKEND_RESOURCE_ID := local
