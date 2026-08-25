# An existing user-managed host reached through its OpenSSH alias. The machine
# may be on-premises or cloud-hosted; Cloudmake never provisions, reconfigures,
# starts, or stops it.
BACKEND_TRANSPORT := ssh
BACKEND_ACCESS_CLASS := user-managed
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := session
BACKEND_CAPABILITIES := sync execute status incremental-sync shell artifacts

SSH_HOST ?=
export SSH_HOST
SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(SSH_BIN) $(RSYNC_BIN) $(PYTHON_BIN)
BACKEND_REQUIRED_VARIABLES := SSH_HOST
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install OpenSSH and rsync; configure a Host alias in ~/.ssh/config; then verify: ssh HOST_ALIAS true
BACKEND_VALIDATE := $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/validate_ssh_host.py'
BACKEND_DOCTOR_PROBE := $(SSH_BIN) $(SSH_OPTIONS) -o BatchMode=yes '$(SSH_HOST)' true
BACKEND_VERSION_COMMAND := $(SSH_BIN) -V
BACKEND_TESTED_CLIENT := OpenSSH-compatible protocol 2 client
BACKEND_RESOURCE_ID := $(SSH_HOST)
BACKEND_REMOTE_REQUIRED_COMMANDS := make rsync tar
BACKEND_STOP_PREREQUISITE := prerequisites
SSH_REFRESH_MESSAGE := SSH connection failed; retrying once without changing user-managed OpenSSH configuration.

# A relative path resolves under the configured remote user's login home and
# therefore requires no provider-specific filesystem or privileged directory.
REMOTE_ROOT ?= .cloudmake/$(PROJECT_SLUG)
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

BACKEND_START := :
BACKEND_STATUS = $(SSH_BIN) $(SSH_OPTIONS) -o BatchMode=yes '$(SSH_HOST)' "printf 'running\n'"
BACKEND_STOP = printf '%s\n' '[ssh] SSH_HOST is user-managed; cloudmake will not stop or reconfigure it.'

.PHONY: refresh-ssh-config
refresh-ssh-config:
	@echo '[ssh] OpenSSH configuration is user-managed; retrying without modification.' >&2
