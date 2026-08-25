# SSH remote control is treated as a paid-tier Colab backend. Colab requires a
# paid plan and a positive compute-unit balance for this managed-runtime access.
BACKEND_TRANSPORT := ssh
BACKEND_ACCESS_CLASS := paid-tier
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := session
BACKEND_CAPABILITIES := sync execute status incremental-sync shell artifacts gpu cancel

COLAB_SESSION ?= cuda-build
COLAB_GPU ?=
COLAB_BIN ?= colab
COLAB_IDENTITY ?= $(firstword $(wildcard $(HOME)/.ssh/id_ed25519 $(HOME)/.ssh/id_ecdsa))
SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(COLAB_BIN) $(SSH_BIN) $(RSYNC_BIN) $(PYTHON_BIN)
BACKEND_REQUIRED_VARIABLES := COLAB_IDENTITY
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install google-colab-cli, OpenSSH, and rsync; Colab SSH also requires a paid plan and positive compute-unit balance.
BACKEND_VALIDATE := case '$(COLAB_SESSION)' in ''|*[!A-Za-z0-9._-]*) echo 'COLAB_SESSION contains unsupported characters' >&2; exit 2;; esac; case '$(COLAB_GPU)' in *[!A-Za-z0-9._-]*) echo 'COLAB_GPU contains unsupported characters' >&2; exit 2;; esac; test -r '$(COLAB_IDENTITY)' || { echo 'COLAB_IDENTITY is not a readable private key: $(COLAB_IDENTITY)' >&2; exit 2; }
BACKEND_DOCTOR_PROBE := $(COLAB_BIN) version >/dev/null && $(COLAB_BIN) sessions >/dev/null
BACKEND_RESOURCE_ID := $(COLAB_SESSION)
BACKEND_REMOTE_REQUIRED_COMMANDS := make rsync tar

COLAB_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/colab-ssh/$(COLAB_SESSION)
COLAB_SSH_CONFIG := $(COLAB_STATE_DIR)/ssh_config
COLAB_SSH_GPU_OPTION := $(if $(strip $(COLAB_GPU)),--gpu $(COLAB_GPU),)

SSH_HOST := colab.$(COLAB_SESSION)
SSH_OPTIONS := -F $(COLAB_SSH_CONFIG)

REMOTE_ROOT ?= /content/.cloudmake/$(PROJECT_SLUG)
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

BACKEND_PREREQUISITE := $(COLAB_SSH_CONFIG)
BACKEND_START := :
BACKEND_STATUS = $(COLAB_BIN) status -s $(COLAB_SESSION)
BACKEND_STOP = $(COLAB_BIN) stop -s $(COLAB_SESSION)

$(COLAB_SSH_CONFIG): doctor
	@if test -z '$(COLAB_BIN)'; then \
		echo 'colab was not found on PATH' >&2; \
		exit 2; \
	fi
	@if test -z '$(COLAB_IDENTITY)'; then \
		echo 'Set COLAB_IDENTITY to an Ed25519 or ECDSA SSH private key' >&2; \
		exit 2; \
	fi
	@mkdir -p '$(COLAB_STATE_DIR)'
	@{ \
		echo 'Host $(SSH_HOST)'; \
		echo '    User root'; \
		echo '    ProxyCommand $(COLAB_BIN) ssh --proxy-mode -s $(COLAB_SESSION) $(COLAB_SSH_GPU_OPTION) -i $(COLAB_IDENTITY)'; \
		echo '    IdentityFile $(COLAB_IDENTITY)'; \
		echo '    IdentitiesOnly yes'; \
		echo '    StrictHostKeyChecking no'; \
		echo '    UserKnownHostsFile /dev/null'; \
		echo '    LogLevel ERROR'; \
	} > '$@.tmp'
	@mv '$@.tmp' '$@'

.PHONY: refresh-ssh-config
refresh-ssh-config: doctor
	@$(MAKE) --no-print-directory -B '$(COLAB_SSH_CONFIG)'
