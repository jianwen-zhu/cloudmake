# GitHub Codespaces exposes a conventional SSH execution surface.
BACKEND_TRANSPORT := ssh
BACKEND_ACCESS_CLASS := quota-tier
BACKEND_API_VERSION := 1
BACKEND_PRODUCT_STATUS := supported
BACKEND_SESSION_REUSE := yes
BACKEND_LIFECYCLE_CONTROL := provider-managed
BACKEND_WORKSPACE_DURABILITY := stop-persistent
BACKEND_OCI_NATIVE := yes
BACKEND_CAPABILITIES := sync execute status incremental-sync shell artifacts cancel native-persistence oci-runner
BACKEND_OCI_RUNTIMES := none
BACKEND_INTERNET_INBOUND := conditional
BACKEND_INTERNET_OUTBOUND := conditional

# Required: the permanent Codespaces name shown by `gh codespace list`.
CODESPACE ?=
GH_BIN ?= gh
SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(GH_BIN) $(SSH_BIN) $(RSYNC_BIN) $(PYTHON_BIN)
BACKEND_REQUIRED_VARIABLES := CODESPACE
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install GitHub CLI, OpenSSH, and rsync; then run: gh auth refresh -h github.com -s codespace
BACKEND_VALIDATE := case '$(CODESPACE)' in ''|*[!A-Za-z0-9._-]*) echo 'CODESPACE contains unsupported characters' >&2; exit 2;; esac
BACKEND_DOCTOR_PROBE := $(GH_BIN) auth status -h github.com >/dev/null && $(GH_BIN) codespace view -c $(CODESPACE) >/dev/null
BACKEND_VERSION_COMMAND := $(GH_BIN) --version
BACKEND_TESTED_CLIENT := GitHub CLI 2.55.x
BACKEND_RESOURCE_ID := $(CODESPACE)
BACKEND_CONTEXT_RESOURCE_LABEL := codespace
BACKEND_REMOTE_REQUIRED_COMMANDS := make rsync tar

CODESPACE_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/codespaces-ssh/$(CODESPACE)
CODESPACE_SSH_CONFIG := $(CODESPACE_STATE_DIR)/ssh_config
CODESPACE_RESOURCE_STATE := $(CODESPACE_STATE_DIR)/resource-state
CODESPACE_ENVIRONMENT_RECEIPT := $(CODESPACE_STATE_DIR)/environment.json

# `gh codespace ssh --config` chooses the canonical Host alias. Resolve it
# lazily because the config file is created as a Make prerequisite.
SSH_HOST = $(shell awk '$$1 == "Host" { print $$2; exit }' $(CODESPACE_SSH_CONFIG) 2>/dev/null)
SSH_OPTIONS := -F $(CODESPACE_SSH_CONFIG)

REMOTE_ROOT ?= /workspaces/.cloudmake/$(PROJECT_SLUG)
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

BACKEND_PREREQUISITE := $(CODESPACE_SSH_CONFIG)
BACKEND_CONTEXT_RESOURCE_STATE_FILE := $(CODESPACE_RESOURCE_STATE)
BACKEND_PRE_CONNECT = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/codespaces_state.py' \
	--gh '$(GH_BIN)' --codespace '$(CODESPACE)' --output '$(CODESPACE_RESOURCE_STATE)' && \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/codespaces_environment.py' \
	--gh '$(GH_BIN)' --codespace '$(CODESPACE)' --mode '$(CLOUDMAKE_RUNNER)' \
	--image-b64 '$(CLOUDMAKE_OCI_IMAGE_B64)' \
	--native-config '$(CLOUDMAKE_TOOL_ROOT)/.devcontainer/devcontainer.json' \
	--native-dockerfile '$(CLOUDMAKE_TOOL_ROOT)/.devcontainer/Dockerfile' \
	--receipt '$(CODESPACE_ENVIRONMENT_RECEIPT)'
BACKEND_OCI_REMOTE_REQUIRED_COMMANDS := make rsync tar

# Connecting over SSH starts a stopped codespace, so no separate start command
# is necessary. The common SSH transport verifies the connection with `ssh true`.
BACKEND_START := :
BACKEND_STATUS = $(GH_BIN) codespace view -c $(CODESPACE)
BACKEND_STOP = $(GH_BIN) codespace stop -c $(CODESPACE)

$(CODESPACE_SSH_CONFIG): doctor
	@if test -z '$(CODESPACE)'; then \
		echo 'Set CODESPACE to the permanent name from: gh codespace list' >&2; \
		exit 2; \
	fi
	@mkdir -p '$(CODESPACE_STATE_DIR)'
	@$(GH_BIN) codespace ssh --config -c '$(CODESPACE)' > '$@.tmp'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/validate_ssh_config.py' '$@.tmp'
	@mv '$@.tmp' '$@'

.PHONY: refresh-ssh-config
refresh-ssh-config: doctor
	@if test -z '$(CODESPACE)'; then \
		echo 'Set CODESPACE to the permanent name from: gh codespace list' >&2; \
		exit 2; \
	fi
	@mkdir -p '$(CODESPACE_STATE_DIR)'
	@$(GH_BIN) codespace ssh --config -c '$(CODESPACE)' > '$(CODESPACE_SSH_CONFIG).tmp'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/validate_ssh_config.py' '$(CODESPACE_SSH_CONFIG).tmp'
	@mv '$(CODESPACE_SSH_CONFIG).tmp' '$(CODESPACE_SSH_CONFIG)'
