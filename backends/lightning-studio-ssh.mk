# Lightning Studios are persistent workspaces with a conventional SSH surface.
# The provider client owns authentication and the SSH key; cloudmake only
# references the key and a generated connection entry.
BACKEND_TRANSPORT := ssh
BACKEND_ACCESS_CLASS := quota-tier
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := session
BACKEND_CAPABILITIES := sync execute status incremental-sync shell artifacts gpu cancel persistent-storage

LIGHTNING_STUDIO ?=
LIGHTNING_TEAMSPACE ?=
LIGHTNING_MACHINE ?= CPU
LIGHTNING_BIN ?= lightning
LIGHTNING_IDENTITY ?= $(HOME)/.ssh/lightning_rsa
SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(LIGHTNING_BIN) $(SSH_BIN) $(RSYNC_BIN) $(PYTHON_BIN)
BACKEND_REQUIRED_VARIABLES := LIGHTNING_STUDIO LIGHTNING_TEAMSPACE
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install lightning-sdk, run: lightning login; create or enable Studio access; then run: lightning ssh configure --name STUDIO --teamspace OWNER/TEAMSPACE
BACKEND_VALIDATE := case '$(LIGHTNING_STUDIO)' in ''|*[!A-Za-z0-9._-]*) echo 'LIGHTNING_STUDIO contains unsupported characters' >&2; exit 2;; esac; case '$(LIGHTNING_TEAMSPACE)' in */*) :;; *) echo 'LIGHTNING_TEAMSPACE must use OWNER/TEAMSPACE form' >&2; exit 2;; esac; case '$(LIGHTNING_TEAMSPACE)' in *[!A-Za-z0-9._/-]*|*/*/*) echo 'LIGHTNING_TEAMSPACE contains unsupported characters' >&2; exit 2;; esac; case '$(LIGHTNING_MACHINE)' in ''|*[!A-Za-z0-9._-]*) echo 'LIGHTNING_MACHINE contains unsupported characters' >&2; exit 2;; esac; test -r '$(LIGHTNING_IDENTITY)' || { echo 'LIGHTNING_IDENTITY is not a readable provider-owned SSH key: $(LIGHTNING_IDENTITY)' >&2; echo 'Run: lightning ssh configure --name $(LIGHTNING_STUDIO) --teamspace $(LIGHTNING_TEAMSPACE)' >&2; exit 2; }
BACKEND_DOCTOR_PROBE := $(LIGHTNING_BIN) auth whoami --json >/dev/null && $(LIGHTNING_BIN) studio list --teamspace '$(LIGHTNING_TEAMSPACE)' --json >/dev/null
BACKEND_VERSION_COMMAND := $(LIGHTNING_BIN) --version
BACKEND_TESTED_CLIENT := lightning-sdk 2026.8.x
LIGHTNING_RESOURCE_ID := $(subst /,--,$(LIGHTNING_TEAMSPACE))--$(LIGHTNING_STUDIO)
BACKEND_RESOURCE_ID := $(LIGHTNING_RESOURCE_ID)
BACKEND_REMOTE_REQUIRED_COMMANDS := make rsync tar

LIGHTNING_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/lightning-studio-ssh/$(LIGHTNING_RESOURCE_ID)
LIGHTNING_SSH_CONFIG := $(LIGHTNING_STATE_DIR)/ssh_config

SSH_HOST := $(LIGHTNING_STUDIO)
SSH_OPTIONS := -F $(LIGHTNING_SSH_CONFIG)

REMOTE_ROOT ?= /teamspace/studios/this_studio/.cloudmake/$(PROJECT_SLUG)
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

BACKEND_PREREQUISITE := $(LIGHTNING_SSH_CONFIG)
BACKEND_START = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/lightning_ensure_studio.py' --client '$(LIGHTNING_BIN)' --teamspace '$(LIGHTNING_TEAMSPACE)' --name '$(LIGHTNING_STUDIO)' --machine '$(LIGHTNING_MACHINE)'
BACKEND_STATUS = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/lightning_studio_status.py' --client '$(LIGHTNING_BIN)' --teamspace '$(LIGHTNING_TEAMSPACE)' --name '$(LIGHTNING_STUDIO)'
BACKEND_STOP = $(LIGHTNING_BIN) studio stop --name '$(LIGHTNING_STUDIO)' --teamspace '$(LIGHTNING_TEAMSPACE)'

$(LIGHTNING_SSH_CONFIG): doctor
	@mkdir -p '$(LIGHTNING_STATE_DIR)'
	@$(LIGHTNING_BIN) ssh generate --name '$(LIGHTNING_STUDIO)' --teamspace '$(LIGHTNING_TEAMSPACE)' > '$@.provider'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/rewrite_ssh_identity.py' \
		--input '$@.provider' --output '$@.tmp' --identity '$(LIGHTNING_IDENTITY)'
	@rm -f '$@.provider'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/validate_ssh_config.py' '$@.tmp'
	@mv '$@.tmp' '$@'

.PHONY: refresh-ssh-config
refresh-ssh-config: doctor
	@rm -f '$(LIGHTNING_SSH_CONFIG)'
	@$(MAKE) --no-print-directory '$(LIGHTNING_SSH_CONFIG)'
