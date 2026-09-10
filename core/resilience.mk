# Shared safety and backend-contract layer. It intentionally uses only Python's
# standard library so every transport has the same local behavior.

CLOUDMAKE_BACKEND_API_VERSION := 1
CLOUDMAKE_STATE_ROOT ?= .cloud-state
CLOUDMAKE_CACHE_ROOT ?= $(CLOUDMAKE_STATE_ROOT)/cache
CLOUDMAKE_IDENTITY_DIR ?= $(CLOUDMAKE_STATE_ROOT)/identity
CLOUDMAKE_OWNER_FILE := $(CLOUDMAKE_IDENTITY_DIR)/owner.json
CLOUDMAKE_OWNER_ID_FILE := $(CLOUDMAKE_IDENTITY_DIR)/owner.id
CLOUDMAKE_LOCK_TIMEOUT ?= 30
CLOUDMAKE_LOCK_FILE_OVERRIDE ?=
CLOUDMAKE_ADOPT ?= 0
CLOUDMAKE_PROJECT_ROOT ?= $(PROJECT_DIR)
CLOUDMAKE_PROJECT_ARGS_B64 ?= W10=
CLOUDMAKE_CONTEXT_ACCELERATOR ?=
CLOUDMAKE_RUNNER ?= native
CLOUDMAKE_OCI_IMAGE_B64 ?=
CLOUDMAKE_OCI_DEVICES_B64 ?= W10=
CLOUDMAKE_OCI_RUNTIMES_B64 ?= W10=
CLOUDMAKE_OCI_ENVIRONMENT_B64 ?= W10=
CLOUDMAKE_HOST_REQUIREMENTS_B64 ?= e30=
CLOUDMAKE_FORWARD_PORTS_B64 ?= W10=
CLOUDMAKE_DEVCONTAINER_ACTIVE ?=
CLOUDMAKE_OCI_RUNTIME ?= auto
CLOUDMAKE_RUN_ID ?=
CLOUDMAKE_OPERATION_STATE ?= $(CLOUDMAKE_STATE_ROOT)/operations/$(if $(CLOUDMAKE_RUN_ID),$(CLOUDMAKE_RUN_ID),manual).json
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
CLOUDMAKE_RECORD_STATE = $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/run_state.py' --file '$(CLOUDMAKE_OPERATION_STATE)'

BACKEND_API_VERSION ?=
# BACKEND_LIFECYCLE is accepted only as an API-1 compatibility input. New
# descriptors declare the single behavior Cloudmake needs to know directly.
BACKEND_LIFECYCLE ?=
BACKEND_PRODUCT_STATUS ?= supported
BACKEND_PRODUCT_STATUS_REASON ?=
BACKEND_SESSION_REUSE ?= $(if $(filter batch,$(BACKEND_LIFECYCLE)),no,$(if $(filter local session,$(BACKEND_LIFECYCLE)),yes,))
# API-1 backends predating v2.2 remain valid and explicitly unqualified. These
# two orthogonal properties describe control authority and working-filesystem
# lifetime without changing the public target surface.
BACKEND_LIFECYCLE_CONTROL ?= unknown
BACKEND_WORKSPACE_DURABILITY ?= unknown
BACKEND_CAPABILITIES ?=
BACKEND_OCI_RUNTIMES ?=
# A native OCI backend asks the provider to construct its execution environment
# from the selected image. API-1 descriptors pre-dating this distinction retain
# the existing adapter behavior.
BACKEND_OCI_NATIVE ?= no
# Public Internet reachability is independent of the provider control
# transport.  A notebook backend can accept authenticated command submission
# while exposing no inbound socket at all.  API-1 descriptors that predate
# these declarations remain valid and report unknown until qualified.
BACKEND_INTERNET_INBOUND ?= unknown
BACKEND_INTERNET_OUTBOUND ?= unknown
BACKEND_RESOURCE_ID ?= default
BACKEND_CONTEXT_RESOURCE_LABEL ?= resource
BACKEND_CONTEXT_RESOURCE ?= $(BACKEND_RESOURCE_ID)
BACKEND_CONTEXT_ACCELERATOR ?= $(CLOUDMAKE_CONTEXT_ACCELERATOR)
BACKEND_CONTEXT_RESOURCE_STATE ?=
BACKEND_CONTEXT_RESOURCE_STATE_FILE ?=
BACKEND_CONTEXT_RUNNER ?= $(if $(filter-out native,$(CLOUDMAKE_RUNNER)),$(CLOUDMAKE_RUNNER),)
BACKEND_CONTEXT_WORKSTATION ?= $(if $(strip $(CLOUDMAKE_DEVCONTAINER_ACTIVE)),devcontainer,)

# A compact, backend-neutral execution banner. Callers may set the shell
# variable CLOUDMAKE_RESOURCE_STATE when they discover started/reused state at
# runtime; otherwise the backend's static state is used.
CLOUDMAKE_PRINT_CONTEXT = \
	printf '[cloudmake] backend=%s' '$(BACKEND)'; \
	if test -n '$(BACKEND_CONTEXT_RUNNER)'; then \
		printf ' runner=%s' '$(BACKEND_CONTEXT_RUNNER)'; \
	fi; \
	if test -n '$(BACKEND_CONTEXT_WORKSTATION)'; then \
		printf ' workstation=%s' '$(BACKEND_CONTEXT_WORKSTATION)'; \
	fi; \
	if test -n '$(BACKEND_CONTEXT_ACCELERATOR)'; then \
		printf ' accelerator=%s' '$(BACKEND_CONTEXT_ACCELERATOR)'; \
	fi; \
	if test -n '$(BACKEND_CONTEXT_RESOURCE)'; then \
		printf ' %s=%s' '$(BACKEND_CONTEXT_RESOURCE_LABEL)' '$(BACKEND_CONTEXT_RESOURCE)'; \
	fi; \
	context_state="$${CLOUDMAKE_RESOURCE_STATE:-$(BACKEND_CONTEXT_RESOURCE_STATE)}"; \
	if test -n "$$context_state"; then printf ' resource=%s' "$$context_state"; fi; \
	printf '\n'

ifeq ($(strip $(BACKEND_API_VERSION)),)
$(error Backend "$(BACKEND)" does not declare BACKEND_API_VERSION)
endif
ifneq ($(BACKEND_API_VERSION),$(CLOUDMAKE_BACKEND_API_VERSION))
$(error Backend "$(BACKEND)" uses API $(BACKEND_API_VERSION); cloudmake supports $(CLOUDMAKE_BACKEND_API_VERSION))
endif
ifeq ($(filter $(BACKEND_PRODUCT_STATUS),supported deprecated),)
$(error Backend "$(BACKEND)" has invalid BACKEND_PRODUCT_STATUS "$(BACKEND_PRODUCT_STATUS)"; expected supported or deprecated)
endif
ifeq ($(filter $(BACKEND_SESSION_REUSE),yes no),)
$(error Backend "$(BACKEND)" has invalid BACKEND_SESSION_REUSE "$(BACKEND_SESSION_REUSE)"; expected yes or no)
endif
ifeq ($(filter $(BACKEND_LIFECYCLE_CONTROL),local provider-managed externally-managed per-target unknown),)
$(error Backend "$(BACKEND)" has invalid BACKEND_LIFECYCLE_CONTROL "$(BACKEND_LIFECYCLE_CONTROL)")
endif
ifeq ($(filter $(BACKEND_WORKSPACE_DURABILITY),ephemeral stop-persistent host-persistent unknown),)
$(error Backend "$(BACKEND)" has invalid BACKEND_WORKSPACE_DURABILITY "$(BACKEND_WORKSPACE_DURABILITY)")
endif
ifeq ($(filter $(BACKEND_OCI_NATIVE),yes no),)
$(error Backend "$(BACKEND)" has invalid BACKEND_OCI_NATIVE "$(BACKEND_OCI_NATIVE)"; expected yes or no)
endif
ifeq ($(strip $(BACKEND_OCI_RUNTIMES)),)
$(error Backend "$(BACKEND)" does not declare BACKEND_OCI_RUNTIMES)
endif
ifneq ($(filter-out none podman docker nerdctl proot crun,$(BACKEND_OCI_RUNTIMES)),)
$(error Backend "$(BACKEND)" has invalid BACKEND_OCI_RUNTIMES "$(BACKEND_OCI_RUNTIMES)")
endif
ifneq ($(filter none,$(BACKEND_OCI_RUNTIMES)),)
ifneq ($(words $(BACKEND_OCI_RUNTIMES)),1)
$(error Backend "$(BACKEND)" must declare OCI runtime "none" alone)
endif
endif
ifeq ($(BACKEND_OCI_NATIVE),yes)
ifneq ($(BACKEND_OCI_RUNTIMES),none)
$(error Backend "$(BACKEND)" with BACKEND_OCI_NATIVE=yes must declare OCI runtime "none")
endif
endif
ifneq ($(filter-out yes no conditional inherited unknown,$(BACKEND_INTERNET_INBOUND)),)
$(error Backend "$(BACKEND)" has invalid BACKEND_INTERNET_INBOUND "$(BACKEND_INTERNET_INBOUND)")
endif
ifneq ($(filter-out yes no conditional inherited unknown,$(BACKEND_INTERNET_OUTBOUND)),)
$(error Backend "$(BACKEND)" has invalid BACKEND_INTERNET_OUTBOUND "$(BACKEND_INTERNET_OUTBOUND)")
endif

CLOUDMAKE_LOCK_FILE := $(if $(strip $(CLOUDMAKE_LOCK_FILE_OVERRIDE)),$(CLOUDMAKE_LOCK_FILE_OVERRIDE),$(CLOUDMAKE_STATE_ROOT)/locks/$(BACKEND)/$(BACKEND_RESOURCE_ID).lock)
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
	@echo 'product-status=$(BACKEND_PRODUCT_STATUS)'
	@echo 'product-status-reason=$(BACKEND_PRODUCT_STATUS_REASON)'
	@echo 'session-reuse=$(BACKEND_SESSION_REUSE)'
	@echo 'lifecycle-control=$(BACKEND_LIFECYCLE_CONTROL)'
	@echo 'workspace-durability=$(BACKEND_WORKSPACE_DURABILITY)'
	@echo 'oci-native=$(BACKEND_OCI_NATIVE)'
	@echo 'transport=$(BACKEND_TRANSPORT)'
	@echo 'capabilities=$(BACKEND_CAPABILITIES)'
	@echo 'oci-runtimes=$(BACKEND_OCI_RUNTIMES)'
	@echo 'internet-inbound=$(BACKEND_INTERNET_INBOUND)'
	@echo 'internet-outbound=$(BACKEND_INTERNET_OUTBOUND)'

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
