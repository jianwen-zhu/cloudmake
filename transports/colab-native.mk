COLAB_STATE_DIR := $(CLOUDMAKE_STATE_ROOT)/colab-notebook/$(COLAB_SESSION)
COLAB_ARCHIVE := $(COLAB_STATE_DIR)/source.tar.gz
COLAB_FINGERPRINT := $(COLAB_STATE_DIR)/source.sha256
COLAB_REMOTE_FINGERPRINT_COPY := $(COLAB_STATE_DIR)/remote-source.sha256
COLAB_REMOTE_OWNER_COPY := $(COLAB_STATE_DIR)/remote-owner.json
COLAB_CONTROL_STATE_COPY := $(COLAB_STATE_DIR)/remote-control-state.txt
COLAB_TARGET_FILE := $(COLAB_STATE_DIR)/target
COLAB_TARGET_RESULT := $(COLAB_STATE_DIR)/target-result.json
COLAB_ARTIFACT_ARCHIVE := $(COLAB_STATE_DIR)/artifacts.tar.gz
COLAB_RUN_NOTEBOOK := $(COLAB_STATE_DIR)/runner.ipynb
COLAB_RESOURCE_STATE := $(COLAB_STATE_DIR)/resource-state

COLAB_REMOTE_ROOT := /content/.cloud-build/workspace
COLAB_REMOTE_ARCHIVE := /content/cloud-build-source.tar.gz
COLAB_REMOTE_FINGERPRINT_INCOMING := /content/cloud-build-source.sha256
COLAB_REMOTE_FINGERPRINT := $(COLAB_REMOTE_ROOT)/source.sha256
COLAB_REMOTE_OWNER_INCOMING := /content/cloud-build-owner.json
COLAB_REMOTE_OWNER := $(COLAB_REMOTE_ROOT)/.cloudmake-owner.json
COLAB_REMOTE_PREPARED_INCOMING := /content/cloud-build-prepared
COLAB_REMOTE_PREPARED := $(COLAB_REMOTE_ROOT)/.cloudmake-prepared
COLAB_REMOTE_TARGET := /content/cloud-build-target
COLAB_REMOTE_TARGET_RESULT := /content/.cloud-build/target-result.json
COLAB_REMOTE_ARTIFACTS := /content/.cloud-build/artifacts.tar.gz

COLAB_INVOCATION_ID := $(if $(CLOUDMAKE_RUN_ID),$(CLOUDMAKE_RUN_ID),manual)
COLAB_CREATED_MARKER := $(COLAB_STATE_DIR)/created-$(COLAB_INVOCATION_ID)
COLAB_RESET_MARKER := $(COLAB_STATE_DIR)/fresh-runtime-$(COLAB_INVOCATION_ID)
COLAB_PREPARED_COPY := $(COLAB_STATE_DIR)/remote-prepared
COLAB_PREPARED_RECEIPT := $(COLAB_STATE_DIR)/prepared
COLAB_PREPARE_TARGET_FILE := $(COLAB_STATE_DIR)/prepare-target

COLAB_ACCELERATOR := $(if $(strip $(COLAB_GPU)),--gpu $(COLAB_GPU),)

.PHONY: help start status stop sync collect dispatch fetch shell open \
	_colab-start _colab-sync _colab-prepare _colab-execute _colab-collect _colab-fetch \
	_colab-fetch-ready _colab-open _colab-stop

help:
	@echo 'Usage: make BACKEND=colab-notebook <target>'
	@echo 'Transport: native Colab contents/kernel APIs (no SSH or Git remote)'
	@echo 'Local backend: local (direct project Make invocation)'
	@echo 'Notebook backends: colab-notebook, kaggle-notebook'
	@echo 'SSH backends: colab-ssh, codespaces-ssh, host-ssh, lightning-studio-ssh'
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
	@rm -f '$(COLAB_CREATED_MARKER)' '$(COLAB_RESET_MARKER)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_lifecycle.py' \
		--client '$(COLAB_BIN)' --session '$(COLAB_SESSION)' \
		$(if $(strip $(COLAB_GPU)),--gpu '$(COLAB_GPU)') \
		--probe-file '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_prerequisites.py' \
		--command-timeout '$(COLAB_READY_PROBE_TIMEOUT)' \
		--ready-timeout '$(COLAB_READY_TIMEOUT)' \
		--poll-seconds '$(COLAB_READY_POLL_SECONDS)' \
		--state-file '$(CLOUDMAKE_OPERATION_STATE)' \
		--created-marker '$(COLAB_CREATED_MARKER)' \
		--resource-state '$(COLAB_RESOURCE_STATE)'
	@resource_state="$$(cat '$(COLAB_RESOURCE_STATE)')"; \
		CLOUDMAKE_RESOURCE_STATE=$$resource_state; $(CLOUDMAKE_PRINT_CONTEXT)

_colab-sync: _colab-start | $(COLAB_STATE_DIR)
	@set -e; \
	$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state ready \
		--target-submission not_submitted --retry-safe true; \
	rm -f '$(COLAB_CONTROL_STATE_COPY)' '$(COLAB_CONTROL_STATE_COPY).tmp'; \
	if ! $(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_READY_PROBE_TIMEOUT)' \
		-f '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_control_state.py' \
		> '$(COLAB_CONTROL_STATE_COPY).tmp' 2>&1; then \
		cat '$(COLAB_CONTROL_STATE_COPY).tmp' >&2; \
		rm -f '$(COLAB_CONTROL_STATE_COPY).tmp'; \
		$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state unknown \
			--runtime-state unreachable --target-submission not_submitted \
			--retry-safe true --failure-code control_state_unreachable; \
		echo '[colab] Remote ownership state could not be verified; synchronization was refused and the target was not submitted.' >&2; \
		echo '[colab] Retrying is safe. Next: cloudmake -b colab --status' >&2; \
		exit 74; \
	fi; \
	mv '$(COLAB_CONTROL_STATE_COPY).tmp' '$(COLAB_CONTROL_STATE_COPY)'; \
	cat '$(COLAB_CONTROL_STATE_COPY)'; \
	if ! owner_state="$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_control_state.py' \
		--parse '$(COLAB_CONTROL_STATE_COPY)' --field owner )"; then \
		$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state unknown \
			--runtime-state unreachable --target-submission not_submitted \
			--retry-safe true --failure-code control_state_invalid; \
		echo '[colab] Remote ownership probe was inconclusive; synchronization was refused and the target was not submitted.' >&2; \
		exit 74; \
	fi; \
	if test "$$owner_state" = present; then \
		if ! $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
			'$(COLAB_REMOTE_OWNER)' '$(COLAB_REMOTE_OWNER_COPY).tmp' >/dev/null 2>&1 || \
			test ! -s '$(COLAB_REMOTE_OWNER_COPY).tmp'; then \
			rm -f '$(COLAB_REMOTE_OWNER_COPY).tmp'; \
			$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state unknown \
				--runtime-state unreachable --target-submission not_submitted \
				--retry-safe true --failure-code owner_record_unreadable; \
			echo '[colab] The remote owner exists but could not be read; synchronization was refused and the target was not submitted.' >&2; \
			echo '[colab] Retrying is safe. Next: cloudmake -b colab --status' >&2; \
			exit 74; \
		fi; \
		mv '$(COLAB_REMOTE_OWNER_COPY).tmp' '$(COLAB_REMOTE_OWNER_COPY)'; \
		adopt=''; test '$(CLOUDMAKE_ADOPT)' = 1 && adopt='--adopt' || :; \
		if ! $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/project_identity.py' check \
			--expected '$(CLOUDMAKE_OWNER_FILE)' \
			--actual '$(COLAB_REMOTE_OWNER_COPY)' \
			--resource 'Colab session $(COLAB_SESSION)' $$adopt; then \
			$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state ready \
				--runtime-state foreign --target-submission not_submitted \
				--retry-safe true --failure-code foreign_workspace; exit 73; \
		fi; \
		$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state ready \
			--runtime-state same --target-submission not_submitted --retry-safe true; \
	else \
		rm -f '$(COLAB_REMOTE_OWNER_COPY).tmp' '$(COLAB_REMOTE_OWNER_COPY)'; \
		touch '$(COLAB_RESET_MARKER)'; \
		if test -f '$(COLAB_CREATED_MARKER)'; then lifecycle=fresh; else lifecycle=reset; fi; \
		echo "[colab] Detected $$lifecycle runtime: remote Cloudmake ownership state is absent." >&2; \
		echo '[colab] A full source sync is required; runtime-local generated state may be gone.' >&2; \
		$(CLOUDMAKE_RECORD_STATE) --phase ownership --provider-state ready \
			--runtime-state $$lifecycle --target-submission not_submitted --retry-safe true; \
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
	$(CLOUDMAKE_RECORD_STATE) --phase synchronization --provider-state ready \
		--target-submission not_submitted --retry-safe true; \
	remote_fingerprint=''; \
	if ! fingerprint_state="$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_control_state.py' \
		--parse '$(COLAB_CONTROL_STATE_COPY)' --field fingerprint )"; then \
		$(CLOUDMAKE_RECORD_STATE) --phase synchronization --provider-state unknown \
			--runtime-state unreachable --target-submission not_submitted \
			--retry-safe true --failure-code control_state_invalid; exit 74; \
	fi; \
	if test ! -f '$(COLAB_RESET_MARKER)' && test "$$fingerprint_state" = present; then \
		if ! $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
			'$(COLAB_REMOTE_FINGERPRINT)' '$(COLAB_REMOTE_FINGERPRINT_COPY)' \
			>/dev/null 2>&1; then \
			$(CLOUDMAKE_RECORD_STATE) --phase synchronization --provider-state unknown \
				--runtime-state unreachable --target-submission not_submitted \
				--retry-safe true --failure-code fingerprint_unreadable; \
			echo '[colab] The remote fingerprint exists but could not be read; synchronization was refused and the target was not submitted.' >&2; \
			echo '[colab] Retrying is safe. Next: cloudmake -b colab --status' >&2; \
			exit 74; \
		fi; \
		remote_fingerprint=1; \
	fi; \
	if test "$$remote_fingerprint" = 1 && \
		cmp -s '$(COLAB_FINGERPRINT)' '$(COLAB_REMOTE_FINGERPRINT_COPY)'; then \
		echo '[colab] Source unchanged; skipping archive upload.'; \
		mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'; \
	else \
		if test ! -f '$(COLAB_RESET_MARKER)' && test "$$fingerprint_state" = absent && \
			test -f '$(COLAB_REMOTE_OWNER_COPY)'; then \
			touch '$(COLAB_RESET_MARKER)'; \
			echo '[colab] Remote fingerprint state is absent; performing a full source sync.' >&2; \
			$(CLOUDMAKE_RECORD_STATE) --phase synchronization --provider-state ready \
				--runtime-state reset --target-submission not_submitted --retry-safe true; \
		fi; \
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

_colab-prepare: _colab-sync | $(COLAB_STATE_DIR)
	@set -e; \
	if test -z '$(COLAB_SESSION_PREPARE_TARGET)'; then exit 0; fi; \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_prepare_receipt.py' \
		--target '$(COLAB_SESSION_PREPARE_TARGET)' \
		--source-fingerprint '$(COLAB_FINGERPRINT)' \
		--output '$(COLAB_PREPARED_RECEIPT)'; \
	prepared=''; \
	if test ! -f '$(COLAB_RESET_MARKER)' && \
		$(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_PREPARED)' '$(COLAB_PREPARED_COPY)' >/dev/null 2>&1 && \
		cmp -s '$(COLAB_PREPARED_RECEIPT)' '$(COLAB_PREPARED_COPY)'; then prepared=1; fi; \
	if test "$$prepared" = 1; then \
		echo '[colab] Session preparation is current; skipping the preparation target.'; \
		exit 0; \
	fi; \
	echo '[colab] Running declared idempotent session preparation target: $(COLAB_SESSION_PREPARE_TARGET)' >&2; \
	$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state ready \
		--preparation-state ambiguous --target-submission not_submitted --retry-safe true; \
	printf '%s\n%s\n%s\n%s\n%s\n' \
		"$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/encode_value.py' '$(COLAB_SESSION_PREPARE_TARGET)' )" \
		'$(JOBS)' '$(PROJECT_MAKEFILE)' 'W10=' '' > '$(COLAB_PREPARE_TARGET_FILE).tmp'; \
	mv '$(COLAB_PREPARE_TARGET_FILE).tmp' '$(COLAB_PREPARE_TARGET_FILE)'; \
	cp '$(COLAB_NOTEBOOK)' '$(COLAB_RUN_NOTEBOOK).tmp'; mv '$(COLAB_RUN_NOTEBOOK).tmp' '$(COLAB_RUN_NOTEBOOK)'; \
	$(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
		'$(COLAB_PREPARE_TARGET_FILE)' '$(COLAB_REMOTE_TARGET)'; \
	if ! $(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
		-f '$(COLAB_RUN_NOTEBOOK)'; then \
		$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state unknown \
			--preparation-state ambiguous --target-submission not_submitted \
			--retry-safe true --failure-code preparation_ambiguous; \
		echo '[colab] Session preparation outcome is ambiguous; the requested target was not submitted.' >&2; \
		exit 1; \
	fi; \
	rm -f '$(COLAB_TARGET_RESULT)' '$(COLAB_TARGET_RESULT).tmp'; \
	if ! $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_TARGET_RESULT)' '$(COLAB_TARGET_RESULT).tmp'; then \
		$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state unknown \
			--preparation-state ambiguous --target-submission not_submitted \
			--retry-safe true --failure-code preparation_result_unavailable; \
		echo '[colab] Session preparation receipt is unavailable; the requested target was not submitted.' >&2; \
		exit 1; \
	fi; \
	mv '$(COLAB_TARGET_RESULT).tmp' '$(COLAB_TARGET_RESULT)'; \
	if ! $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/target_result.py' \
		--result '$(COLAB_TARGET_RESULT)'; then \
		$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state failed \
			--preparation-state failed --target-submission not_submitted \
			--retry-safe true --failure-code preparation_failed; \
		echo '[colab] Session preparation failed; the requested target was not submitted.' >&2; \
		exit 1; \
	fi; \
	if ! $(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
		'$(COLAB_PREPARED_RECEIPT)' '$(COLAB_REMOTE_PREPARED_INCOMING)'; then \
		$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state unknown \
			--preparation-state succeeded --target-submission not_submitted \
			--retry-safe true --failure-code preparation_receipt_upload_failed; \
		echo '[colab] Preparation succeeded, but its receipt upload failed; the requested target was not submitted and retrying is safe.' >&2; \
		exit 1; \
	fi; \
	if ! $(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
		-f '$(CLOUDMAKE_TOOL_ROOT)/tools/colab_prepare.py'; then \
		$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state unknown \
			--preparation-state ambiguous --target-submission not_submitted \
			--retry-safe true --failure-code preparation_receipt_install_ambiguous; \
		echo '[colab] Preparation receipt installation is ambiguous; the requested target was not submitted and retrying is safe.' >&2; \
		exit 1; \
	fi; \
	$(CLOUDMAKE_RECORD_STATE) --phase preparation --provider-state ready \
		--preparation-state succeeded --target-submission not_submitted --retry-safe true

_colab-execute: _colab-prepare | $(COLAB_STATE_DIR)
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
	@$(CLOUDMAKE_RECORD_STATE) --phase target_submission --provider-state ready \
		--target-submission not_submitted --retry-safe true
	@set +e; $(COLAB_BIN) upload -s '$(COLAB_SESSION)' \
		'$(COLAB_TARGET_FILE)' '$(COLAB_REMOTE_TARGET)'; code=$$?; \
	if test $$code -ne 0; then \
		$(CLOUDMAKE_RECORD_STATE) --phase target_submission --provider-state unknown \
			--target-submission not_submitted --retry-safe true \
			--failure-code target_request_upload_failed; \
		echo '[colab] Target request upload failed before submission; retrying the command is safe.' >&2; \
	fi; exit $$code
	@$(CLOUDMAKE_RECORD_STATE) --phase target_execution --provider-state running \
		--target-submission ambiguous --retry-safe false
	@set +e; \
	$(COLAB_BIN) exec -s '$(COLAB_SESSION)' --timeout '$(COLAB_TIMEOUT)' \
		-f '$(COLAB_RUN_NOTEBOOK)'; \
	exec_status=$$?; \
	printf '%s\n' '[cloudmake] notebook=$(COLAB_RUN_NOTEBOOK)'; \
	if test $$exec_status -ne 0; then \
		printf '[cloudmake] infrastructure failure: notebook execution exited with status %s\n' "$$exec_status" >&2; \
		$(CLOUDMAKE_RECORD_STATE) --phase target_execution --provider-state unknown \
			--target-submission ambiguous --retry-safe false \
			--failure-code ambiguous_execution; \
		echo '[colab] Automatic replay is unsafe. Next: cloudmake -b colab --status' >&2; \
		created=false; test -f '$(COLAB_CREATED_MARKER)' && created=true || :; \
		echo "[cloudmake] failure phase=target_execution provider_state=unknown session_created=$$created target_submission=ambiguous retry_safe=false" >&2; \
	else \
		$(CLOUDMAKE_RECORD_STATE) --phase target_execution --provider-state ready \
			--target-submission submitted --retry-safe false; \
	fi; \
	exit $$exec_status
	@rm -f '$(COLAB_TARGET_RESULT)' '$(COLAB_TARGET_RESULT).tmp'
	@set +e; \
	$(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_TARGET_RESULT)' '$(COLAB_TARGET_RESULT).tmp'; \
	download_status=$$?; \
	if test $$download_status -ne 0; then \
		printf '[cloudmake] infrastructure failure: target result receipt download exited with status %s\n' "$$download_status" >&2; \
		$(CLOUDMAKE_RECORD_STATE) --phase target_execution --provider-state unknown \
			--target-submission submitted --retry-safe false \
			--failure-code target_result_unavailable; \
		rm -f '$(COLAB_TARGET_RESULT).tmp'; \
	fi; \
	exit $$download_status
	@mv '$(COLAB_TARGET_RESULT).tmp' '$(COLAB_TARGET_RESULT)'
	@set +e; $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/target_result.py' \
		--result '$(COLAB_TARGET_RESULT)'; code=$$?; \
	if test $$code -eq 0; then provider=succeeded; else provider=failed; fi; \
	$(CLOUDMAKE_RECORD_STATE) --phase target_execution --provider-state $$provider \
		--target-submission submitted --retry-safe false; exit $$code

_colab-collect: _colab-execute
	@$(MAKE) --no-print-directory _colab-fetch-ready

_colab-fetch: _colab-start | $(COLAB_STATE_DIR)
	@$(MAKE) --no-print-directory _colab-fetch-ready

_colab-fetch-ready: | $(COLAB_STATE_DIR)
	@$(CLOUDMAKE_RECORD_STATE) --phase artifact_retrieval --provider-state ready \
		--target-submission submitted --retry-safe false
	@set +e; $(COLAB_BIN) download -s '$(COLAB_SESSION)' \
		'$(COLAB_REMOTE_ARTIFACTS)' '$(COLAB_ARTIFACT_ARCHIVE).tmp'; code=$$?; \
	if test $$code -ne 0; then \
		$(CLOUDMAKE_RECORD_STATE) --phase artifact_retrieval --provider-state unknown \
			--target-submission submitted --retry-safe false \
			--failure-code artifact_download_failed; \
		echo '[colab] Artifact retrieval failed; the target will not be replayed. Next: cloudmake -b colab --fetch' >&2; \
	fi; exit $$code
	@mv '$(COLAB_ARTIFACT_ARCHIVE).tmp' '$(COLAB_ARTIFACT_ARCHIVE)'
	$(CLOUDMAKE_SAFE_EXTRACT) \
		--archive '$(COLAB_ARTIFACT_ARCHIVE)' --destination '$(ARTIFACT_DIR)'

_colab-open: _colab-start
	$(COLAB_BIN) url -s '$(COLAB_SESSION)' --open

_colab-stop: ensure-owner
	$(COLAB_BIN) stop -s '$(COLAB_SESSION)'
