# Shared safety and backend-contract layer. It intentionally uses only Python's
# standard library so every transport has the same local behavior.

CLOUDMAKE_BACKEND_API_VERSION := 1
CLOUDMAKE_STATE_ROOT ?= .cloud-state
CLOUDMAKE_CACHE_ROOT ?= $(CLOUDMAKE_STATE_ROOT)/cache
CLOUDMAKE_IDENTITY_DIR ?= $(CLOUDMAKE_STATE_ROOT)/identity
CLOUDMAKE_OWNER_FILE := $(CLOUDMAKE_IDENTITY_DIR)/owner.json
CLOUDMAKE_OWNER_ID_FILE := $(CLOUDMAKE_IDENTITY_DIR)/owner.id
CLOUDMAKE_LOCK_TIMEOUT ?= 30
CLOUDMAKE_ADOPT ?= 0
CLOUDMAKE_PROJECT_ROOT ?= $(PROJECT_DIR)
CLOUDMAKE_PROJECT_ARGS_B64 ?= W10=
SOURCE_WARN_MB ?= 25
SOURCE_MAX_MB ?= 0
CLOUDMAKE_ALLOW_SECRETS ?= 0
CLOUDMAKE_SECRET_OPTION = $(if $(filter 1,$(CLOUDMAKE_ALLOW_SECRETS)),--allow-secrets,)
ARTIFACT_MAX_FILES ?= 50000
ARTIFACT_MAX_MB ?= 2048
ARTIFACT_MAX_FILE_MB ?= 1024
ARTIFACT_MAX_ARCHIVE_MB ?= 1024
ARTIFACT_MAX_RATIO ?= 500

CLOUDMAKE_SAFE_EXTRACT = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/safe_extract.py' \
	--max-files '$(ARTIFACT_MAX_FILES)' --max-total-mb '$(ARTIFACT_MAX_MB)' \
	--max-file-mb '$(ARTIFACT_MAX_FILE_MB)' \
	--max-archive-mb '$(ARTIFACT_MAX_ARCHIVE_MB)' \
	--max-ratio '$(ARTIFACT_MAX_RATIO)'

BACKEND_API_VERSION ?=
BACKEND_LIFECYCLE ?=
BACKEND_CAPABILITIES ?=
BACKEND_RESOURCE_ID ?= default

ifeq ($(strip $(BACKEND_API_VERSION)),)
$(error Backend "$(BACKEND)" does not declare BACKEND_API_VERSION)
endif
ifneq ($(BACKEND_API_VERSION),$(CLOUDMAKE_BACKEND_API_VERSION))
$(error Backend "$(BACKEND)" uses API $(BACKEND_API_VERSION); cloudmake supports $(CLOUDMAKE_BACKEND_API_VERSION))
endif
ifeq ($(filter $(BACKEND_LIFECYCLE),local session batch),)
$(error Backend "$(BACKEND)" has invalid BACKEND_LIFECYCLE "$(BACKEND_LIFECYCLE)")
endif

CLOUDMAKE_LOCK_FILE := $(CLOUDMAKE_STATE_ROOT)/locks/$(BACKEND)/$(BACKEND_RESOURCE_ID).lock
CLOUDMAKE_MANIFEST_DIR := $(CLOUDMAKE_STATE_ROOT)/manifests/$(BACKEND)
CLOUDMAKE_MANIFEST := $(CLOUDMAKE_MANIFEST_DIR)/$(BACKEND_RESOURCE_ID).json
CLOUDMAKE_CURRENT_MANIFEST := $(CLOUDMAKE_MANIFEST).current
CLOUDMAKE_WITH_LOCK = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/with_lock.py' --path '$(CLOUDMAKE_LOCK_FILE)' --timeout '$(CLOUDMAKE_LOCK_TIMEOUT)' --

.PHONY: backend-contract ensure-owner backend-info sync-dry-run

backend-contract:
	@for capability in sync execute status artifacts; do \
		case ' $(BACKEND_CAPABILITIES) ' in *" $$capability "*) : ;; *) \
			echo "Backend $(BACKEND) must declare the $$capability capability." >&2; exit 2 ;; esac; \
	done

ensure-owner: prerequisites
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/project_identity.py' ensure \
		--state-dir '$(CLOUDMAKE_IDENTITY_DIR)' \
		--project-root '$(CLOUDMAKE_PROJECT_ROOT)' \
		--project-name '$(PROJECT)' >/dev/null

backend-info: backend-contract
	@echo 'backend=$(BACKEND)'
	@echo 'api=$(BACKEND_API_VERSION)'
	@echo 'lifecycle=$(BACKEND_LIFECYCLE)'
	@echo 'transport=$(BACKEND_TRANSPORT)'
	@echo 'capabilities=$(BACKEND_CAPABILITIES)'

ifeq ($(BACKEND_TRANSPORT),local)
sync-dry-run: backend-contract
	@echo '[local] The working tree is already local; no source transfer is selected.'
else
sync-dry-run: backend-contract
	@if ! command -v '$(PYTHON_BIN)' >/dev/null 2>&1; then \
		echo 'Missing required command: $(PYTHON_BIN)' >&2; exit 2; fi
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
		--root '$(PROJECT_DIR)' \
		--compare '$(CLOUDMAKE_MANIFEST)' --dry-run \
		$(CLOUDMAKE_SECRET_OPTION) \
		--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)'
endif
