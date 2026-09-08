# Colab notebook backend: native contents and kernel APIs, independent of SSH
# and GitHub/Gist credentials.
BACKEND_TRANSPORT := colab-native
BACKEND_ACCESS_CLASS := notebook
BACKEND_API_VERSION := 1
BACKEND_SESSION_REUSE := yes
BACKEND_CAPABILITIES := sync execute status incremental-sync open artifacts gpu cancel capacity-retry persistent-workspace checkpoint-persistence environment-profile oci-runner
BACKEND_OCI_RUNTIMES := crun
BACKEND_INTERNET_INBOUND := no
BACKEND_INTERNET_OUTBOUND := yes

COLAB_SESSION ?= $(PROJECT_SLUG)
COLAB_GPU ?=
COLAB_TIMEOUT ?= 3600
COLAB_READY_TIMEOUT ?= 120
COLAB_READY_POLL_SECONDS ?= 3
COLAB_READY_PROBE_TIMEOUT ?= 15
COLAB_SESSION_PREPARE_TARGET ?=
COLAB_BIN ?= colab
COLAB_NOTEBOOK ?= $(CLOUDMAKE_TOOL_ROOT)/notebooks/colab.ipynb
PYTHON_BIN ?= python3
CLOUDMAKE_CHECKPOINT ?= 0
CLOUDMAKE_PROJECT_KEY ?=
CLOUDMAKE_WORKSPACE_ID ?= $(CLOUDMAKE_PROJECT_KEY)
CLOUDMAKE_CHECKPOINT_KEYCHAIN ?= $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/checkpoint_keychain.py'

BACKEND_REQUIRED_COMMANDS := $(COLAB_BIN) $(PYTHON_BIN) tar $(if $(filter 1,$(CLOUDMAKE_CHECKPOINT)),openssl)
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install the official CLI with: uv tool install google-colab-cli
BACKEND_VALIDATE := case '$(COLAB_SESSION)' in ''|*[!A-Za-z0-9._-]*) echo 'COLAB_SESSION contains unsupported characters' >&2; exit 2;; esac; case '$(COLAB_GPU)' in *[!A-Za-z0-9._-]*) echo 'COLAB_GPU contains unsupported characters' >&2; exit 2;; esac; case '$(COLAB_TIMEOUT)' in ''|*[!0-9]*) echo 'COLAB_TIMEOUT must be a positive integer' >&2; exit 2;; 0) echo 'COLAB_TIMEOUT must be a positive integer' >&2; exit 2;; esac; case '$(COLAB_READY_TIMEOUT)' in ''|*[!0-9.]*) echo 'COLAB_READY_TIMEOUT must be a positive number' >&2; exit 2;; esac; case '$(COLAB_READY_PROBE_TIMEOUT)' in ''|*[!0-9.]*) echo 'COLAB_READY_PROBE_TIMEOUT must be a positive number' >&2; exit 2;; esac; case '$(COLAB_READY_POLL_SECONDS)' in ''|*[!0-9.]*) echo 'COLAB_READY_POLL_SECONDS must be a non-negative number' >&2; exit 2;; esac; case '$(COLAB_SESSION_PREPARE_TARGET)' in *[!A-Za-z0-9._/-]*) echo 'COLAB_SESSION_PREPARE_TARGET must be a simple Make target name' >&2; exit 2;; esac; if test '$(CLOUDMAKE_CHECKPOINT)' = 1; then $(CLOUDMAKE_CHECKPOINT_KEYCHAIN) check; fi
BACKEND_DOCTOR_PROBE := $(COLAB_BIN) version >/dev/null && $(COLAB_BIN) sessions >/dev/null
BACKEND_VERSION_COMMAND := $(COLAB_BIN) version
BACKEND_TESTED_CLIENT := google-colab-cli 0.6.x
BACKEND_RESOURCE_ID := $(COLAB_SESSION)
BACKEND_CONTEXT_RESOURCE_LABEL := session
BACKEND_CONTEXT_ACCELERATOR := $(if $(strip $(COLAB_GPU)),$(COLAB_GPU),$(CLOUDMAKE_CONTEXT_ACCELERATOR))
COLAB_CHECKPOINT_HOST ?= $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_checkpoint_host.py'
