# An already-provisioned single Google Compute Engine VM. Cloudmake owns the
# operational start/reuse/stop cycle; Google Cloud owns provisioning and disks.
BACKEND_TRANSPORT := ssh
BACKEND_ACCESS_CLASS := paid-tier
BACKEND_API_VERSION := 1
BACKEND_PRODUCT_STATUS := unqualified
BACKEND_PRODUCT_STATUS_REASON := GCP Compute Engine passed the live e2-micro CPU gate; the paid G4 GPU/CDI gate remains pending
BACKEND_SESSION_REUSE := yes
BACKEND_LIFECYCLE_CONTROL := provider-managed
BACKEND_WORKSPACE_DURABILITY := stop-persistent
BACKEND_TARGET_REPLAY := none
BACKEND_OCI_NATIVE := no
BACKEND_CAPABILITIES := sync execute status incremental-sync shell artifacts cancel native-persistence environment-profile oci-runner devcontainer port-forward gpu cdi
BACKEND_OCI_RUNTIMES := docker podman nerdctl proot
BACKEND_DEVCONTAINER_ADAPTER_CAPABILITIES := image-digest environment host-requirements forward-ports cdi security-policy
BACKEND_DEVCONTAINER_NATIVE_CAPABILITIES := none
BACKEND_DEVCONTAINER_REALIZATION_ORDER := adapter
BACKEND_INTERNET_INBOUND := conditional
BACKEND_INTERNET_OUTBOUND := conditional

GCP_PROJECT ?=
GCP_ZONE ?=
GCP_INSTANCE ?=
GCP_TUNNEL_THROUGH_IAP ?= no
GCLOUD_BIN ?= gcloud
SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(GCLOUD_BIN) $(RSYNC_BIN) $(PYTHON_BIN)
BACKEND_REQUIRED_VARIABLES := GCP_PROJECT GCP_ZONE GCP_INSTANCE
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install Google Cloud CLI, run gcloud auth login, and select an already-provisioned Compute Engine VM; see docs/guides/gcp-backend.md
BACKEND_VALIDATE := case '$(GCP_PROJECT)' in ''|*[!A-Za-z0-9._:-]*) echo 'GCP_PROJECT contains unsupported characters' >&2; exit 2;; esac; case '$(GCP_ZONE)' in ''|*[!A-Za-z0-9-]*) echo 'GCP_ZONE contains unsupported characters' >&2; exit 2;; esac; case '$(GCP_INSTANCE)' in ''|*[!A-Za-z0-9-]*) echo 'GCP_INSTANCE contains unsupported characters' >&2; exit 2;; esac; case '$(GCP_TUNNEL_THROUGH_IAP)' in yes|no) :;; *) echo 'GCP_TUNNEL_THROUGH_IAP must be yes or no' >&2; exit 2;; esac
BACKEND_DOCTOR_PROBE := test -n "$$($(GCLOUD_BIN) auth list --filter=status:ACTIVE --format=value\(account\) 2>/dev/null)" && $(GCLOUD_BIN) compute instances describe '$(GCP_INSTANCE)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' --format=value\(name\) >/dev/null
BACKEND_VERSION_COMMAND := $(GCLOUD_BIN) version
BACKEND_TESTED_CLIENT := Google Cloud CLI 540.x
BACKEND_RESOURCE_ID := $(GCP_PROJECT)--$(GCP_ZONE)--$(GCP_INSTANCE)
BACKEND_CONTEXT_RESOURCE_LABEL := instance
BACKEND_CONTEXT_RESOURCE := $(GCP_INSTANCE)
BACKEND_REMOTE_REQUIRED_COMMANDS := make rsync tar

GCP_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/gcp-compute-ssh/$(BACKEND_RESOURCE_ID)
GCP_RESOURCE_STATE := $(GCP_STATE_DIR)/resource-state
GCP_RESOURCE_RECEIPT := $(GCP_STATE_DIR)/resource.json
GCP_SSH_WRAPPER := $(GCP_STATE_DIR)/gcp-ssh
GCP_ENVIRONMENT_PROFILE := $(GCP_STATE_DIR)/environment-profile.json
GCP_CONTROL_DIR := /tmp/cloudmake-gcp-$(shell id -u)
GCP_REMOTE_ENVIRONMENT_TOOL = $(REMOTE_ROOT)/.cloudmake-vm-capabilities.py
GCP_REMOTE_ENVIRONMENT_PROFILE = $(REMOTE_ROOT)/.cloudmake-environment-profile.json

SSH_HOST := $(GCP_INSTANCE)
SSH_BIN := $(GCP_SSH_WRAPPER)
SSH_OPTIONS := -o ControlMaster=auto -o ControlPersist=60 -o ControlPath=$(GCP_CONTROL_DIR)/%C
REMOTE_ROOT ?= .cloudmake/$(PROJECT_SLUG)
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

BACKEND_PREREQUISITE := gcp-connection
BACKEND_CONTEXT_RESOURCE_STATE_FILE := $(GCP_RESOURCE_STATE)
BACKEND_START := :
BACKEND_STATUS = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_lifecycle.py' --gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' --instance '$(GCP_INSTANCE)' --output '$(GCP_RESOURCE_RECEIPT)' --state-file '$(GCP_RESOURCE_STATE)' --status
BACKEND_STOP = if test -x '$(GCP_SSH_WRAPPER)'; then $(GCP_SSH_WRAPPER) -O exit '$(GCP_INSTANCE)' >/dev/null 2>&1 || :; fi; $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_lifecycle.py' --gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' --instance '$(GCP_INSTANCE)' --output '$(GCP_RESOURCE_RECEIPT)' --state-file '$(GCP_RESOURCE_STATE)' --stop

.PHONY: gcp-connection refresh-ssh-config environment _gcp-environment
gcp-connection: doctor
	@mkdir -p '$(GCP_STATE_DIR)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_lifecycle.py' \
		--gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' \
		--instance '$(GCP_INSTANCE)' --output '$(GCP_RESOURCE_RECEIPT)' \
		--state-file '$(GCP_RESOURCE_STATE)' --ensure-running
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_ssh.py' \
		--gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' \
		--instance '$(GCP_INSTANCE)' $(if $(filter yes,$(GCP_TUNNEL_THROUGH_IAP)),--tunnel-through-iap,) \
		--create-wrapper '$(GCP_SSH_WRAPPER)' --python '$(PYTHON_BIN)' \
		--control-directory '$(GCP_CONTROL_DIR)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_ssh.py' \
		--gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' \
		--instance '$(GCP_INSTANCE)' $(if $(filter yes,$(GCP_TUNNEL_THROUGH_IAP)),--tunnel-through-iap,) \
		--wait-ready
	@if test "$$(cat '$(GCP_RESOURCE_STATE)')" = started; then \
		$(SSH) "sh -s -- reset-after-restart '$(REMOTE_LOCK)' restarted 0" \
			< '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh'; \
	fi

refresh-ssh-config: prerequisites
	@rm -f '$(GCP_SSH_WRAPPER)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/gcp_ssh.py' \
		--gcloud '$(GCLOUD_BIN)' --project '$(GCP_PROJECT)' --zone '$(GCP_ZONE)' \
		--instance '$(GCP_INSTANCE)' $(if $(filter yes,$(GCP_TUNNEL_THROUGH_IAP)),--tunnel-through-iap,) \
		--create-wrapper '$(GCP_SSH_WRAPPER)' --python '$(PYTHON_BIN)' \
		--control-directory '$(GCP_CONTROL_DIR)'

environment: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _gcp-environment

_gcp-environment: _ssh-start
	@if ! $(SSH) "command -v python3 >/dev/null 2>&1"; then \
		echo 'Missing required remote command: python3' >&2; exit 2; \
	fi
	@$(SSH) "mkdir -p '$(REMOTE_ROOT)'"
	@$(RSYNC_BIN) -az -e '$(RSYNC_RSH)' \
		'$(CLOUDMAKE_TOOL_ROOT)/tools/vm_capabilities.py' \
		$(SSH_HOST):$(GCP_REMOTE_ENVIRONMENT_TOOL)
	@$(SSH) "python3 '$(GCP_REMOTE_ENVIRONMENT_TOOL)' --workspace '$(REMOTE_SRC)' --result '$(GCP_REMOTE_ENVIRONMENT_PROFILE)' >/dev/null"
	@mkdir -p '$(GCP_STATE_DIR)'
	@$(RSYNC_BIN) -az -e '$(RSYNC_RSH)' \
		$(SSH_HOST):$(GCP_REMOTE_ENVIRONMENT_PROFILE) '$(GCP_ENVIRONMENT_PROFILE).tmp'
	@mv '$(GCP_ENVIRONMENT_PROFILE).tmp' '$(GCP_ENVIRONMENT_PROFILE)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/vm_capabilities.py' \
		--render '$(GCP_ENVIRONMENT_PROFILE)'
