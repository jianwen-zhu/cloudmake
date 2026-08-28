# Kaggle's official CLI runs committed notebook versions as isolated batch jobs.
BACKEND_TRANSPORT := kaggle-kernel
BACKEND_ACCESS_CLASS := notebook-batch
BACKEND_API_VERSION := 1
BACKEND_LIFECYCLE := batch
BACKEND_CAPABILITIES := sync execute status open artifacts gpu batch

KAGGLE_BIN ?= kaggle
KAGGLE_USERNAME ?=
KAGGLE_KERNEL_SLUG ?= $(PROJECT_SLUG)
KAGGLE_KERNEL_TITLE ?= $(subst -, ,$(KAGGLE_KERNEL_SLUG))
KAGGLE_ACCELERATOR ?=
KAGGLE_PRIVATE ?= true
KAGGLE_ENABLE_INTERNET ?= false
KAGGLE_TIMEOUT ?= 3600
KAGGLE_POLL_SECONDS ?= 10
KAGGLE_NOTEBOOK ?= $(CLOUDMAKE_TOOL_ROOT)/notebooks/kaggle.ipynb
PYTHON_BIN ?= python3

BACKEND_REQUIRED_COMMANDS := $(KAGGLE_BIN) $(PYTHON_BIN) tar
BACKEND_REQUIRED_VARIABLES := KAGGLE_USERNAME
BACKEND_REQUIRES_PYTHON := yes
BACKEND_INSTALL_HINT := Install and authenticate with: uv tool install kaggle; kaggle auth login
KAGGLE_VALIDATE_POSITIVE = $(PYTHON_BIN) -c 'import re,sys; value=sys.argv[1]; raise SystemExit(not (re.fullmatch("(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)", value) and float(value) > 0))'
BACKEND_VALIDATE := case '$(KAGGLE_USERNAME)' in ''|*[!A-Za-z0-9._-]*) echo 'KAGGLE_USERNAME contains unsupported characters' >&2; exit 2;; esac; case '$(KAGGLE_KERNEL_SLUG)' in ''|*[!A-Za-z0-9._-]*) echo 'KAGGLE_KERNEL_SLUG contains unsupported characters' >&2; exit 2;; esac; case '$(KAGGLE_ACCELERATOR)' in *[!A-Za-z0-9._-]*) echo 'KAGGLE_ACCELERATOR contains unsupported characters' >&2; exit 2;; esac; $(KAGGLE_VALIDATE_POSITIVE) '$(KAGGLE_TIMEOUT)' || { echo 'KAGGLE_TIMEOUT must be a positive number' >&2; exit 2; }; $(KAGGLE_VALIDATE_POSITIVE) '$(KAGGLE_POLL_SECONDS)' || { echo 'KAGGLE_POLL_SECONDS must be a positive number' >&2; exit 2; }
BACKEND_DOCTOR_PROBE := $(KAGGLE_BIN) --version >/dev/null && $(KAGGLE_BIN) kernels list -m --page-size 1 >/dev/null
BACKEND_VERSION_COMMAND := $(KAGGLE_BIN) --version
BACKEND_TESTED_CLIENT := Kaggle CLI 2.2.x
BACKEND_RESOURCE_ID := $(KAGGLE_KERNEL_SLUG)
BACKEND_CONTEXT_RESOURCE_LABEL := kernel
BACKEND_CONTEXT_RESOURCE = $(KAGGLE_USERNAME)/$(KAGGLE_KERNEL_SLUG)
BACKEND_CONTEXT_ACCELERATOR := $(if $(strip $(KAGGLE_ACCELERATOR)),$(KAGGLE_ACCELERATOR),$(CLOUDMAKE_CONTEXT_ACCELERATOR))
