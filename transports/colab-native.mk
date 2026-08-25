COLAB_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/colab-notebook/$(COLAB_SESSION)
COLAB_ARCHIVE := $(COLAB_STATE_DIR)/source.tar.gz
COLAB_FINGERPRINT := $(COLAB_STATE_DIR)/source.sha256
COLAB_REMOTE_FINGERPRINT_COPY := $(COLAB_STATE_DIR)/remote-source.sha256
COLAB_REMOTE_OWNER_COPY := $(COLAB_STATE_DIR)/remote-owner.json
COLAB_TARGET_FILE := $(COLAB_STATE_DIR)/target
COLAB_ARTIFACT_ARCHIVE := $(COLAB_STATE_DIR)/artifacts.tar.gz
COLAB_RUN_NOTEBOOK := $(COLAB_STATE_DIR)/runner.ipynb

COLAB_REMOTE_ROOT := /content/.cloud-build/workspace
COLAB_REMOTE_ARCHIVE := /content/cloud-build-source.tar.gz
COLAB_REMOTE_FINGERPRINT_INCOMING := /content/cloud-build-source.sha256
COLAB_REMOTE_FINGERPRINT := $(COLAB_REMOTE_ROOT)/source.sha256
COLAB_REMOTE_OWNER_INCOMING := /content/cloud-build-owner.json
COLAB_REMOTE_OWNER := $(COLAB_REMOTE_ROOT)/.cloudmake-owner.json
COLAB_REMOTE_TARGET := /content/cloud-build-target
COLAB_REMOTE_ARTIFACTS := /content/.cloud-build/artifacts.tar.gz

COLAB_ACCELERATOR := $(if $(strip $(COLAB_GPU)),--gpu $(COLAB_GPU),)

.PHONY: help start status stop sync collect dispatch fetch shell open \
	_colab-start _colab-sync _colab-execute _colab-collect _colab-fetch \
	_colab-fetch-ready _colab-open _colab-stop

help:
	@echo 'Usage: make BACKEND=colab-notebook <target>'
	@echo 'Transport: native Colab contents/kernel APIs (no SSH or Git remote)'
	@echo 'Notebook backends: colab-notebook, kaggle-notebook'
	@echo 'SSH backends: colab-ssh, codespaces-ssh, lab-ssh, lightning-studio-ssh'
	@echo
	@echo 'Targets:'
	@echo '  prerequisites  Check required local commands and settings'
	@echo '  doctor   Check prerequisites plus Colab authentication (no allocation)'
	@echo '  start    Create or reuse the named Colab session'
	@echo '  sync     Upload the current working tree through colab upload'
	@echo '  sync-dry-run  Show selected source changes without contacting Colab'
	@echo '  dispatch  Internal arbitrary project-target execution (launcher managed)'
	@echo '  collect  Run REMOTE_TARGET, collect REMOTE_COLLECT_DIR_B64, and fetch it'
	@echo '  fetch    Download and safely extract prepared artifacts'
	@echo '  open     Open the same CLI-owned runtime in Colab'
	@echo '  stop     Release the runtime'

start: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-start

status: doctor
	@mkdir -p '$(CLOUDMAKE_STATE_ROOT)/status'
	@set -e; temporary='$(CLOUDMAKE_STATE_ROOT)/status/$(BACKEND)-$$$$.tmp'; \
		if $(COLAB_BIN) status -s '$(COLAB_SESSION)' > "$$temporary" 2>&1; then \
			cat "$$temporary"; \
			$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/normalize_status.py' --backend '$(BACKEND)' < "$$temporary"; \
			rm -f "$$temporary"; \
		else code=$$?; cat "$$temporary"; rm -f "$$temporary"; exit $$code; fi

stop: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-stop

sync: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-sync

dispatch: doctor
	@if test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET_B64 is required for dispatch' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-execute

collect: doctor
	@if test -z '$(REMOTE_TARGET)' && test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET or REMOTE_TARGET_B64 is required for collect' >&2; exit 2; fi
	@if test -z '$(REMOTE_COLLECT_DIR_B64)'; then echo 'REMOTE_COLLECT_DIR_B64 is required for collect' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-collect

fetch: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-fetch

open: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _colab-open

shell:
	@echo 'The native Colab backend intentionally has no SSH shell.' >&2
	@echo 'Use "make BACKEND=colab-notebook open" for the notebook execution surface.' >&2
	@exit 2

$(COLAB_STATE_DIR):
	mkdir -p '$@'

_colab-start: ensure-owner | $(COLAB_STATE_DIR)
	@if ! $(COLAB_BIN) sessions 2>/dev/null | \
		awk -v session='$(COLAB_SESSION)' \
		'$$1 == "[" session "]" { found = 1 } END { exit !found }'; then \
		$(COLAB_BIN) new -s '$(COLAB_SESSION)' $(COLAB_ACCELERATOR); \
	fi
	@set -e; \
	if ! $(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
		-f '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_prerequisites.py'; then \
		echo '[colab] Readiness connection failed; retrying the non-mutating probe once.' >&2; \
		if ! $(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
			-f '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_prerequisites.py'; then \
			echo '[colab] The named session remains unreachable; refusing automatic recreation because remote ownership is ambiguous.' >&2; \
			echo '[colab] Inspect cloudmake --status, then use cloudmake --stop and retry only after verifying the session.' >&2; \
			exit 1; \
		fi; \
	fi

_colab-sync: _colab-start | $(COLAB_STATE_DIR)
	@set -e; \
	if $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_OWNER)' '$(COLAB_REMOTE_OWNER_COPY).tmp' >/dev/null 2>&1 && \
		test -s '$(COLAB_REMOTE_OWNER_COPY).tmp'; then \
		mv '$(COLAB_REMOTE_OWNER_COPY).tmp' '$(COLAB_REMOTE_OWNER_COPY)'; \
		adopt=''; test '$(CLOUDMAKE_ADOPT)' = 1 && adopt='--adopt' || :; \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/project_identity.py' check \
			--expected '$(CLOUDMAKE_OWNER_FILE)' \
			--actual '$(COLAB_REMOTE_OWNER_COPY)' \
			--resource 'Colab session $(COLAB_SESSION)' $$adopt; \
	else \
		rm -f '$(COLAB_REMOTE_OWNER_COPY).tmp' '$(COLAB_REMOTE_OWNER_COPY)'; \
	fi
	@mkdir -p '$(CLOUDMAKE_MANIFEST_DIR)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
		--root '$(PROJECT_DIR)' \
		--manifest '$(CLOUDMAKE_CURRENT_MANIFEST)' \
		$(CLOUDMAKE_SECRET_OPTION) \
		--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)' \
		> '$(COLAB_FINGERPRINT).tmp'
	@mv '$(COLAB_FINGERPRINT).tmp' '$(COLAB_FINGERPRINT)'
	@set -e; \
	if $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_FINGERPRINT)' '$(COLAB_REMOTE_FINGERPRINT_COPY)' \
		>/dev/null 2>&1 && \
		cmp -s '$(COLAB_FINGERPRINT)' '$(COLAB_REMOTE_FINGERPRINT_COPY)'; then \
		echo '[colab] Source unchanged; skipping archive upload.'; \
		mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'; \
	else \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
			--root '$(PROJECT_DIR)' \
			--archive '$(COLAB_ARCHIVE)' \
			$(CLOUDMAKE_SECRET_OPTION) \
			--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)' >/dev/null; \
		$(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
			'$(COLAB_ARCHIVE)' '$(COLAB_REMOTE_ARCHIVE)'; \
		$(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
			'$(COLAB_FINGERPRINT)' '$(COLAB_REMOTE_FINGERPRINT_INCOMING)'; \
		$(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
			'$(CLOUDMAKE_OWNER_FILE)' '$(COLAB_REMOTE_OWNER_INCOMING)'; \
		$(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
			-f '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_sync.py'; \
		mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'; \
	fi

_colab-execute: _colab-sync | $(COLAB_STATE_DIR)
	@set -e; target_b64='$(REMOTE_TARGET_B64)'; \
		if test -z "$$target_b64"; then \
			target_b64="$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/encode_value.py' '$(REMOTE_TARGET)' )"; \
		fi; \
		printf '%s\n%s\n%s\n%s\n%s\n' \
			"$$target_b64" '$(JOBS)' '$(PROJECT_MAKEFILE)' \
			'$(CLOUDMAKE_PROJECT_ARGS_B64)' '$(REMOTE_COLLECT_DIR_B64)' \
			> '$(COLAB_TARGET_FILE).tmp'
	@mv '$(COLAB_TARGET_FILE).tmp' '$(COLAB_TARGET_FILE)'
	@cp '$(COLAB_NOTEBOOK)' '$(COLAB_RUN_NOTEBOOK).tmp'
	@mv '$(COLAB_RUN_NOTEBOOK).tmp' '$(COLAB_RUN_NOTEBOOK)'
	$(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
		'$(COLAB_TARGET_FILE)' '$(COLAB_REMOTE_TARGET)'
	$(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
		-f '$(COLAB_RUN_NOTEBOOK)'

_colab-collect: _colab-execute
	@$(MAKE) --no-print-directory _colab-fetch-ready

_colab-fetch: _colab-start | $(COLAB_STATE_DIR)
	@$(MAKE) --no-print-directory _colab-fetch-ready

_colab-fetch-ready: | $(COLAB_STATE_DIR)
	$(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_ARTIFACTS)' '$(COLAB_ARTIFACT_ARCHIVE).tmp'
	@mv '$(COLAB_ARTIFACT_ARCHIVE).tmp' '$(COLAB_ARTIFACT_ARCHIVE)'
	$(CLOUDMAKE_SAFE_EXTRACT) \
		--archive '$(COLAB_ARTIFACT_ARCHIVE)' --destination '$(ARTIFACT_DIR)'

_colab-open: _colab-start
	$(COLAB_BIN) url -s '$(COLAB_SESSION)' --open

_colab-stop: ensure-owner
	$(COLAB_BIN) stop -s '$(COLAB_SESSION)'
