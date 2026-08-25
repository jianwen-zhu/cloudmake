KAGGLE_KERNEL_REF := $(KAGGLE_USERNAME)/$(KAGGLE_KERNEL_SLUG)
KAGGLE_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/kaggle-notebook/$(KAGGLE_KERNEL_SLUG)
KAGGLE_KERNEL_DIR := $(KAGGLE_STATE_DIR)/kernel
KAGGLE_OUTPUT_DIR := $(KAGGLE_STATE_DIR)/output
KAGGLE_ARCHIVE := $(KAGGLE_STATE_DIR)/source.tar.gz
KAGGLE_FINGERPRINT := $(KAGGLE_STATE_DIR)/source.sha256
KAGGLE_CURRENT_FINGERPRINT := $(KAGGLE_STATE_DIR)/source.current.sha256
KAGGLE_RUN_LOG := $(KAGGLE_OUTPUT_DIR)/cloud-build.log
KAGGLE_ARTIFACT_ARCHIVE := $(KAGGLE_OUTPUT_DIR)/artifacts.tar.gz

KAGGLE_ACCELERATOR_OPTION := $(if $(strip $(KAGGLE_ACCELERATOR)),--accelerator $(KAGGLE_ACCELERATOR),)

.PHONY: help start status stop sync collect dispatch fetch shell open \
	_kaggle-start _kaggle-sync _kaggle-execute _kaggle-collect _kaggle-fetch _kaggle-open

help:
	@echo 'Usage: make BACKEND=kaggle-notebook KAGGLE_USERNAME=<name> <target>'
	@echo 'Transport: private Kaggle notebook versions (fresh batch VM per run)'
	@echo
	@echo 'Targets:'
	@echo '  prerequisites  Check required local commands and settings'
	@echo '  doctor   Check prerequisites plus Kaggle authentication (no allocation)'
	@echo '  start    Verify Kaggle CLI authentication; allocates no compute'
	@echo '  sync     Refresh the cached source archive when local content changes'
	@echo '  sync-dry-run  Show selected source changes without contacting Kaggle'
	@echo '  dispatch  Internal arbitrary project-target execution (launcher managed)'
	@echo '  collect  Run REMOTE_TARGET, collect REMOTE_COLLECT_DIR_B64, and fetch it'
	@echo '  fetch    Safely replace artifacts from the latest completed version'
	@echo '  status   Show the latest submitted notebook version status'
	@echo '  open     Open the private notebook page'
	@echo '  stop     No-op: Kaggle batch VMs terminate after the version finishes'

$(KAGGLE_STATE_DIR) $(KAGGLE_KERNEL_DIR) $(KAGGLE_OUTPUT_DIR):
	mkdir -p '$@'

start: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-start

status: doctor
	@$(MAKE) --no-print-directory _kaggle-start
	@mkdir -p '$(CLOUDMAKE_STATE_ROOT)/status'
	@set -e; temporary='$(CLOUDMAKE_STATE_ROOT)/status/$(BACKEND)-$$$$.tmp'; \
		if $(KAGGLE_BIN) kernels status '$(KAGGLE_KERNEL_REF)' > "$$temporary" 2>&1; then \
			cat "$$temporary"; \
			$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/normalize_status.py' --backend '$(BACKEND)' < "$$temporary"; \
			rm -f "$$temporary"; \
		else code=$$?; cat "$$temporary"; rm -f "$$temporary"; exit $$code; fi

stop:
	@echo '[kaggle] Notebook versions are batch jobs and release their VM automatically.'

sync: prerequisites
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-sync

dispatch: doctor
	@if test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET_B64 is required for dispatch' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-execute

collect: doctor
	@if test -z '$(REMOTE_TARGET)' && test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET or REMOTE_TARGET_B64 is required for collect' >&2; exit 2; fi
	@if test -z '$(REMOTE_COLLECT_DIR_B64)'; then echo 'REMOTE_COLLECT_DIR_B64 is required for collect' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-collect

fetch: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-fetch

open: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-open

shell:
	@echo 'Kaggle kernel submission is a batch notebook surface, not a remote shell.' >&2
	@exit 2

_kaggle-start: ensure-owner
	@$(KAGGLE_BIN) kernels list -m --page-size 1 >/dev/null

_kaggle-sync: ensure-owner | $(KAGGLE_STATE_DIR)
	@mkdir -p '$(CLOUDMAKE_MANIFEST_DIR)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
		--root '$(PROJECT_DIR)' \
		--manifest '$(CLOUDMAKE_CURRENT_MANIFEST)' \
		$(CLOUDMAKE_SECRET_OPTION) \
		--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)' \
		> '$(KAGGLE_CURRENT_FINGERPRINT).tmp'
	@mv '$(KAGGLE_CURRENT_FINGERPRINT).tmp' '$(KAGGLE_CURRENT_FINGERPRINT)'
	@set -e; \
	if test -f '$(KAGGLE_ARCHIVE)' && test -f '$(KAGGLE_FINGERPRINT)' && \
		cmp -s '$(KAGGLE_CURRENT_FINGERPRINT)' '$(KAGGLE_FINGERPRINT)'; then \
		echo '[kaggle] Source unchanged; reusing cached source archive.'; \
		mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'; \
	else \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
			--root '$(PROJECT_DIR)' \
			--archive '$(KAGGLE_ARCHIVE)' \
			$(CLOUDMAKE_SECRET_OPTION) \
			--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)' >/dev/null; \
		mv '$(KAGGLE_CURRENT_FINGERPRINT)' '$(KAGGLE_FINGERPRINT)'; \
		mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'; \
		echo '[kaggle] Refreshed cached source archive.'; \
	fi

_kaggle-execute: _kaggle-start _kaggle-sync | $(KAGGLE_KERNEL_DIR) $(KAGGLE_OUTPUT_DIR)
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_prepare.py' \
		--template '$(KAGGLE_NOTEBOOK)' \
		--archive '$(KAGGLE_ARCHIVE)' \
		--owner '$(CLOUDMAKE_OWNER_FILE)' \
		--output '$(KAGGLE_KERNEL_DIR)/runner.ipynb' \
		--metadata '$(KAGGLE_KERNEL_DIR)/kernel-metadata.json' \
		--kernel-ref '$(KAGGLE_KERNEL_REF)' \
		--title '$(KAGGLE_KERNEL_TITLE)' \
		--target '$(REMOTE_TARGET)' \
		--target-b64 '$(REMOTE_TARGET_B64)' \
		--jobs '$(JOBS)' \
		--makefile '$(PROJECT_MAKEFILE)' \
		--arguments-b64 '$(CLOUDMAKE_PROJECT_ARGS_B64)' \
		--collect-dir-b64 '$(REMOTE_COLLECT_DIR_B64)' \
		--private '$(KAGGLE_PRIVATE)' \
		--enable-internet '$(KAGGLE_ENABLE_INTERNET)' \
		--accelerator '$(KAGGLE_ACCELERATOR)'
	$(KAGGLE_BIN) kernels push -p '$(KAGGLE_KERNEL_DIR)' \
		--timeout '$(KAGGLE_TIMEOUT)' $(KAGGLE_ACCELERATOR_OPTION)
	@set +e; \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_wait.py' \
		--kaggle '$(KAGGLE_BIN)' \
		--kernel '$(KAGGLE_KERNEL_REF)' \
		--timeout '$(KAGGLE_TIMEOUT)' \
		--poll '$(KAGGLE_POLL_SECONDS)'; \
	wait_status=$$?; \
	$(KAGGLE_BIN) kernels output '$(KAGGLE_KERNEL_REF)' \
		-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'cloud-build[.]log$$'; \
	output_status=$$?; \
	test ! -f '$(KAGGLE_RUN_LOG)' || cat '$(KAGGLE_RUN_LOG)'; \
	if test $$wait_status -ne 0; then exit $$wait_status; fi; \
	exit $$output_status

_kaggle-collect: _kaggle-execute
	@$(MAKE) --no-print-directory _kaggle-fetch

_kaggle-fetch: _kaggle-start | $(KAGGLE_OUTPUT_DIR)
	$(KAGGLE_BIN) kernels output '$(KAGGLE_KERNEL_REF)' \
		-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'artifacts[.]tar[.]gz$$'
	$(CLOUDMAKE_SAFE_EXTRACT) \
		--archive '$(KAGGLE_ARTIFACT_ARCHIVE)' --destination '$(ARTIFACT_DIR)'

_kaggle-open: _kaggle-start
	$(PYTHON_BIN) -m webbrowser -t 'https://www.kaggle.com/code/$(KAGGLE_KERNEL_REF)'
