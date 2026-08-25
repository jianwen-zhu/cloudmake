# Colab notebook backend: native contents and kernel APIs, independent of SSH
# and GitHub/Gist credentials.
BACKEND_TRANSPORT := colab-native
BACKEND_ACCESS_CLASS := notebook
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := session
BACKEND_CAPABILITIES := sync execute status incremental-sync open artifacts gpu cancel

COLAB_SESSION ?= cuda-build
COLAB_GPU ?=
COLAB_TIMEOUT ?= 3600
COLAB_BIN ?= colab
COLAB_NOTEBOOK ?= $(CLOUDMAKE_TOOL_ROOT)/notebooks/colab.ipynb
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(COLAB_BIN) $(PYTHON_BIN) tar
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install the official CLI with: uv tool install google-colab-cli
BACKEND_VALIDATE := case '$(COLAB_SESSION)' in ''|*[!A-Za-z0-9._-]*) echo 'COLAB_SESSION contains unsupported characters' >&2; exit 2;; esac; case '$(COLAB_GPU)' in *[!A-Za-z0-9._-]*) echo 'COLAB_GPU contains unsupported characters' >&2; exit 2;; esac; case '$(COLAB_TIMEOUT)' in ''|*[!0-9]*) echo 'COLAB_TIMEOUT must be a positive integer' >&2; exit 2;; 0) echo 'COLAB_TIMEOUT must be a positive integer' >&2; exit 2;; esac
BACKEND_DOCTOR_PROBE := $(COLAB_BIN) version >/dev/null && $(COLAB_BIN) sessions >/dev/null
BACKEND_VERSION_COMMAND := $(COLAB_BIN) version
BACKEND_TESTED_CLIENT := google-colab-cli 0.6.x
BACKEND_RESOURCE_ID := $(COLAB_SESSION)
