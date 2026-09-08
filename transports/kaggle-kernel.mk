KAGGLE_KERNEL_REF := $(KAGGLE_USERNAME)/$(KAGGLE_KERNEL_SLUG)
KAGGLE_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/kaggle-notebook/$(KAGGLE_KERNEL_SLUG)
KAGGLE_KERNEL_DIR := $(KAGGLE_STATE_DIR)/kernel
KAGGLE_OUTPUT_DIR := $(KAGGLE_STATE_DIR)/output
KAGGLE_ARCHIVE := $(KAGGLE_STATE_DIR)/source.tar.gz
KAGGLE_FINGERPRINT := $(KAGGLE_STATE_DIR)/source.sha256
KAGGLE_CURRENT_FINGERPRINT := $(KAGGLE_STATE_DIR)/source.current.sha256
KAGGLE_RUN_LOG := $(KAGGLE_OUTPUT_DIR)/cloud-build.log
KAGGLE_ARTIFACT_ARCHIVE := $(KAGGLE_OUTPUT_DIR)/artifacts.tar.gz
KAGGLE_DISPATCH := $(KAGGLE_STATE_DIR)/dispatch.json
KAGGLE_TARGET_RESULT := $(KAGGLE_OUTPUT_DIR)/cloudmake-target-result.json
KAGGLE_CHECKPOINT_RESULT := $(KAGGLE_OUTPUT_DIR)/cloudmake-checkpoint-result.json
KAGGLE_OCI_RESULT := $(KAGGLE_OUTPUT_DIR)/cloudmake-oci-result.json
KAGGLE_CHECKPOINT_HEAD := $(KAGGLE_STATE_DIR)/checkpoint/head.json
KAGGLE_CHECKPOINT_STATE_DIR := $(KAGGLE_STATE_DIR)/checkpoint
KAGGLE_CHECKPOINT_PROVENANCE := $(KAGGLE_CHECKPOINT_STATE_DIR)/$(if $(CLOUDMAKE_RUN_ID),$(CLOUDMAKE_RUN_ID),operation)-publish.json

KAGGLE_ACCELERATOR_OPTION := $(if $(strip $(KAGGLE_ACCELERATOR)),--accelerator $(KAGGLE_ACCELERATOR),)

.PHONY: help start status stop sync collect dispatch fetch shell open \
	_kaggle-start _kaggle-sync _kaggle-execute _kaggle-collect _kaggle-fetch _kaggle-open \
	workspace-purge _kaggle-workspace-purge

help:
	@echo 'Usage: make BACKEND=kaggle-notebook KAGGLE_USERNAME=<name> <target>'
	@echo 'Transport: private Kaggle notebook versions (fresh batch VM per run)'
	@echo 'Local backend: local (direct project Make invocation)'
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
	@echo '  workspace-purge  Delete both private checkpoint slots (launcher managed)'

$(KAGGLE_STATE_DIR) $(KAGGLE_KERNEL_DIR) $(KAGGLE_OUTPUT_DIR):
	mkdir -p '$@'

start: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-start

status: doctor
	@$(MAKE) --no-print-directory _kaggle-start
	@mkdir -p '$(CLOUDMAKE_STATE_ROOT)/status'
	@set -e; reference='$(KAGGLE_KERNEL_REF)'; \
		if test '$(CLOUDMAKE_CHECKPOINT)' = 1 && test -f '$(KAGGLE_CHECKPOINT_HEAD)'; then \
			reference=`$(PYTHON_BIN) -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel_ref"])' '$(KAGGLE_CHECKPOINT_HEAD)'`; \
		fi; temporary='$(CLOUDMAKE_STATE_ROOT)/status/$(BACKEND)-$$$$.tmp'; \
		if $(KAGGLE_BIN) kernels status "$$reference" > "$$temporary" 2>&1; then \
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
	@CLOUDMAKE_RESOURCE_STATE=new; $(CLOUDMAKE_PRINT_CONTEXT)
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
		--accelerator '$(KAGGLE_ACCELERATOR)' \
		$(if $(filter 1,$(CLOUDMAKE_CHECKPOINT)),--checkpoint,) \
		--workspace-id '$(CLOUDMAKE_WORKSPACE_ID)' \
		--checkpoint-head '$(KAGGLE_CHECKPOINT_HEAD)' \
		--source-manifest '$(CLOUDMAKE_MANIFEST)' \
		--dispatch '$(KAGGLE_DISPATCH)' \
		--remote-helper '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_remote.py' \
		--oci-helper '$(CLOUDMAKE_TOOL_ROOT)/tools/oci_runner.py' \
		--runner '$(CLOUDMAKE_RUNNER)' \
		--image-b64 '$(CLOUDMAKE_OCI_IMAGE_B64)' \
		--devices-b64 '$(CLOUDMAKE_OCI_DEVICES_B64)' \
		--runtimes-b64 '$(CLOUDMAKE_OCI_RUNTIMES_B64)'
	@$(CLOUDMAKE_RECORD_STATE) --phase provider_submission --provider-state ready \
		--target-submission not_submitted --retry-safe true
	@set +e; $(KAGGLE_BIN) kernels push -p '$(KAGGLE_KERNEL_DIR)' \
		--timeout '$(KAGGLE_TIMEOUT)' $(KAGGLE_ACCELERATOR_OPTION); code=$$?; \
		if test $$code -ne 0; then \
			$(CLOUDMAKE_RECORD_STATE) --phase provider_submission --provider-state unknown \
				--target-submission ambiguous --retry-safe false \
				--failure-code provider_submission_failed; \
			exit $$code; \
		fi; \
		$(CLOUDMAKE_RECORD_STATE) --phase provider_execution --provider-state running \
			--target-submission ambiguous --retry-safe false
	@set +e; \
	reference=`$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_result.py' field --dispatch '$(KAGGLE_DISPATCH)' --field kernel_ref`; \
	rm -f '$(KAGGLE_RUN_LOG)' '$(KAGGLE_TARGET_RESULT)' '$(KAGGLE_CHECKPOINT_RESULT)' '$(KAGGLE_OCI_RESULT)'; \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_wait.py' \
		--kaggle '$(KAGGLE_BIN)' \
		--kernel "$$reference" \
		--timeout '$(KAGGLE_TIMEOUT)' \
		--poll '$(KAGGLE_POLL_SECONDS)'; \
	wait_status=$$?; \
	$(KAGGLE_BIN) kernels output "$$reference" \
		-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'cloud-build[.]log$$'; \
	output_status=$$?; \
	$(KAGGLE_BIN) kernels output "$$reference" \
		-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'cloudmake-target-result[.]json$$'; \
	target_output_status=$$?; \
	if test '$(CLOUDMAKE_CHECKPOINT)' = 1; then \
		$(KAGGLE_BIN) kernels output "$$reference" \
			-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'cloudmake-checkpoint-result[.]json$$'; \
		checkpoint_output_status=$$?; \
	else checkpoint_output_status=0; fi; \
	if test '$(CLOUDMAKE_RUNNER)' = oci; then \
		$(KAGGLE_BIN) kernels output "$$reference" \
			-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'cloudmake-oci-result[.]json$$'; \
		oci_output_status=$$?; \
	else oci_output_status=0; fi; \
	test ! -f '$(KAGGLE_RUN_LOG)' || cat '$(KAGGLE_RUN_LOG)'; \
	if test $$target_output_status -ne 0 || test $$checkpoint_output_status -ne 0 || test $$oci_output_status -ne 0; then \
		if test $$wait_status -ne 0; then exit $$wait_status; fi; exit 70; \
	fi; \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_result.py' complete \
		--dispatch '$(KAGGLE_DISPATCH)' --target-result '$(KAGGLE_TARGET_RESULT)' \
		--operation-state '$(CLOUDMAKE_OPERATION_STATE)' \
		$(if $(filter 1,$(CLOUDMAKE_CHECKPOINT)),--checkpoint-result '$(KAGGLE_CHECKPOINT_RESULT)' --head '$(KAGGLE_CHECKPOINT_HEAD)' --provenance '$(KAGGLE_CHECKPOINT_PROVENANCE)',); \
	result_status=$$?; \
	if test $$wait_status -ne 0 && test $$result_status -eq 0; then \
		$(CLOUDMAKE_RECORD_STATE) --phase provider_execution --provider-state failed \
			--target-submission submitted --retry-safe false \
			--failure-code provider_execution_failed; \
		exit $$wait_status; \
	fi; \
	if test $$output_status -ne 0; then exit $$output_status; fi; \
	exit $$result_status

_kaggle-collect: _kaggle-execute
	@$(MAKE) --no-print-directory _kaggle-fetch

_kaggle-fetch: _kaggle-start | $(KAGGLE_OUTPUT_DIR)
	@set -e; reference='$(KAGGLE_KERNEL_REF)'; \
		if test '$(CLOUDMAKE_CHECKPOINT)' = 1 && test -f '$(KAGGLE_CHECKPOINT_HEAD)'; then \
			reference=`$(PYTHON_BIN) -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel_ref"])' '$(KAGGLE_CHECKPOINT_HEAD)'`; \
		fi; \
		$(KAGGLE_BIN) kernels output "$$reference" \
			-p '$(KAGGLE_OUTPUT_DIR)' -o --file-pattern 'artifacts[.]tar[.]gz$$'
	$(CLOUDMAKE_SAFE_EXTRACT) \
		--archive '$(KAGGLE_ARTIFACT_ARCHIVE)' --destination '$(ARTIFACT_DIR)'

_kaggle-open: _kaggle-start
	@reference='$(KAGGLE_KERNEL_REF)'; \
	if test '$(CLOUDMAKE_CHECKPOINT)' = 1 && test -f '$(KAGGLE_CHECKPOINT_HEAD)'; then \
		reference=`$(PYTHON_BIN) -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel_ref"])' '$(KAGGLE_CHECKPOINT_HEAD)'`; \
	fi; $(PYTHON_BIN) -m webbrowser -t "https://www.kaggle.com/code/$$reference"

workspace-purge: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _kaggle-workspace-purge

_kaggle-workspace-purge: ensure-owner
	@set -e; listing='$(KAGGLE_CHECKPOINT_STATE_DIR)/purge-kernels.json'; \
		references='$(KAGGLE_CHECKPOINT_STATE_DIR)/purge-refs.txt'; \
		mkdir -p '$(KAGGLE_CHECKPOINT_STATE_DIR)'; \
		trap 'rm -f "$$listing" "$$references"' EXIT HUP INT TERM; \
		$(KAGGLE_BIN) kernels list -m --page-size 200 \
			--search 'cloudmake-ws-$(CLOUDMAKE_WORKSPACE_ID)' --format json > "$$listing"; \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/kaggle_result.py' slots \
			--listing "$$listing" --owner '$(KAGGLE_USERNAME)' \
			--workspace-id '$(CLOUDMAKE_WORKSPACE_ID)' > "$$references"; \
		while IFS= read -r reference; do \
			$(KAGGLE_BIN) kernels delete -y "$$reference"; \
		done < "$$references"; \
		rm -f '$(KAGGLE_CHECKPOINT_HEAD)'; \
	echo '[kaggle] Deleted private checkpoint kernel slots for workspace $(CLOUDMAKE_WORKSPACE_ID).'
