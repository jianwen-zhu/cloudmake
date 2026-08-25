REMOTE_SRC := $(REMOTE_ROOT)/src
REMOTE_OWNER_FILE := $(REMOTE_ROOT)/.cloudmake-owner.json
REMOTE_LOCK := $(REMOTE_ROOT)/.cloudmake-lock
REMOTE_ARTIFACT_ARCHIVE := $(REMOTE_ROOT)/.cloudmake-artifacts.tar.gz
REMOTE_LOCK_STALE ?= 7200

SSH_BIN ?= ssh
RSYNC_BIN ?= rsync
SSH_OPTIONS ?=
BACKEND_PREREQUISITE ?=
BACKEND_START ?= :
BACKEND_STATUS ?= :
BACKEND_STOP ?= :
BACKEND_REMOTE_REQUIRED_COMMANDS ?= make rsync tar
REMOTE_MAKEFILE ?= $(PROJECT_MAKEFILE)

# SSH_HOST may be discovered from a configuration file generated as a target
# prerequisite. Keep this recursive so it is resolved after that file exists.
SSH = $(SSH_BIN) $(SSH_OPTIONS) $(SSH_HOST)
RSYNC_RSH := $(SSH_BIN) $(SSH_OPTIONS)
SSH_REMOTE_OWNER_COPY := $(CLOUDMAKE_STATE_ROOT)/$(BACKEND)/$(BACKEND_RESOURCE_ID)/remote-owner.json
CLOUDMAKE_RSYNC_IGNORE := $(if $(wildcard $(PROJECT_DIR)/.cloudmakeignore),--exclude-from='$(PROJECT_DIR)/.cloudmakeignore',)
SSH_ARTIFACT_ARCHIVE := $(CLOUDMAKE_STATE_ROOT)/$(BACKEND)/$(BACKEND_RESOURCE_ID)/artifacts.tar.gz

.PHONY: help start status stop sync build test run collect dispatch fetch shell open \
	_ssh-start _ssh-sync _ssh-sync-unlocked _ssh-execute _ssh-fetch _ssh-shell _ssh-stop

help:
	@echo 'Usage: make BACKEND=<name> <target>'
	@echo 'Notebook backends: colab-notebook (default), kaggle-notebook'
	@echo 'SSH backends: colab-ssh, codespaces-ssh'
	@echo
	@echo 'Targets: start status stop sync build test run collect fetch shell'
	@echo '         sync-dry-run prerequisites doctor backend-info'

start: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-start

status: doctor
	@mkdir -p '$(CLOUDMAKE_STATE_ROOT)/status'
	@set -e; temporary='$(CLOUDMAKE_STATE_ROOT)/status/$(BACKEND)-$$$$.tmp'; \
		if $(BACKEND_STATUS) > "$$temporary" 2>&1; then \
			cat "$$temporary"; \
			$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/normalize_status.py' --backend '$(BACKEND)' < "$$temporary"; \
			rm -f "$$temporary"; \
		else code=$$?; cat "$$temporary"; rm -f "$$temporary"; exit $$code; fi

stop: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-stop

sync: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-sync

build test run: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-execute REMOTE_TARGET='$@'

dispatch: doctor
	@if test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET_B64 is required for dispatch' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-execute

collect: doctor
	@if test -z '$(REMOTE_TARGET)' && test -z '$(REMOTE_TARGET_B64)'; then echo 'REMOTE_TARGET or REMOTE_TARGET_B64 is required for collect' >&2; exit 2; fi
	@if test -z '$(REMOTE_COLLECT_DIR_B64)'; then echo 'REMOTE_COLLECT_DIR_B64 is required for collect' >&2; exit 2; fi
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-collect

fetch: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-fetch

shell: doctor
	@$(CLOUDMAKE_WITH_LOCK) $(MAKE) --no-print-directory _ssh-shell

open:
	@echo 'The $(BACKEND) backend uses SSH; run: make BACKEND=$(BACKEND) shell'

_ssh-start: ensure-owner $(BACKEND_PREREQUISITE)
	@$(BACKEND_START)
	@if ! $(SSH) true; then \
		echo '[cloudmake] SSH connection failed; refreshing generated configuration once.' >&2; \
		$(MAKE) --no-print-directory refresh-ssh-config; \
		$(SSH) true; \
	fi
	@missing=0; \
	for command in $(BACKEND_REMOTE_REQUIRED_COMMANDS); do \
		if ! $(SSH) "command -v '$$command' >/dev/null 2>&1"; then \
			echo "Missing required remote command: $$command" >&2; \
			missing=1; \
		fi; \
	done; \
	if test "$$missing" -ne 0; then \
		echo 'Install the missing tool in the remote image before running cloudmake.' >&2; \
		exit 2; \
	fi

_ssh-sync: _ssh-start
	@set -eu; \
	token="$$(cat '$(CLOUDMAKE_OWNER_ID_FILE)')-$$$$-$$(date +%s)"; \
	$(SSH) "mkdir -p '$(REMOTE_ROOT)' && sh -s -- acquire '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh'; \
	cleanup() { $(SSH) "sh -s -- release '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh' >/dev/null 2>&1 || :; }; \
	trap cleanup EXIT HUP INT TERM; \
	$(MAKE) --no-print-directory _ssh-sync-unlocked

_ssh-sync-unlocked: ensure-owner $(BACKEND_PREREQUISITE)
	@mkdir -p '$(dir $(SSH_REMOTE_OWNER_COPY))'
	@mkdir -p '$(CLOUDMAKE_MANIFEST_DIR)'
	@$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/source_fingerprint.py' \
		--root '$(PROJECT_DIR)' \
		--manifest '$(CLOUDMAKE_CURRENT_MANIFEST)' \
		--warn-mb '$(SOURCE_WARN_MB)' --max-mb '$(SOURCE_MAX_MB)' >/dev/null
	@set -eu; \
	temporary='$(SSH_REMOTE_OWNER_COPY).tmp'; \
	if $(SSH) "cat '$(REMOTE_OWNER_FILE)'" > "$$temporary" 2>/dev/null && test -s "$$temporary"; then \
		mv "$$temporary" '$(SSH_REMOTE_OWNER_COPY)'; \
		adopt=''; test '$(CLOUDMAKE_ADOPT)' = 1 && adopt='--adopt' || :; \
		$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/project_identity.py' check \
			--expected '$(CLOUDMAKE_OWNER_FILE)' \
			--actual '$(SSH_REMOTE_OWNER_COPY)' \
			--resource '$(BACKEND) workspace $(REMOTE_ROOT)' $$adopt; \
	else \
		rm -f "$$temporary" '$(SSH_REMOTE_OWNER_COPY)'; \
	fi
	$(SSH) 'mkdir -p $(REMOTE_SRC)'
	$(RSYNC_BIN) -az --delete \
		--exclude='/.git/' \
		--exclude='/.cloud-state/' \
		--exclude='/artifacts/' \
		$(CLOUDMAKE_RSYNC_IGNORE) \
		-e '$(RSYNC_RSH)' \
		'$(PROJECT_DIR)/' $(SSH_HOST):$(REMOTE_SRC)/
	$(RSYNC_BIN) -az -e '$(RSYNC_RSH)' \
		'$(CLOUDMAKE_OWNER_FILE)' $(SSH_HOST):$(REMOTE_OWNER_FILE)
	@mv '$(CLOUDMAKE_CURRENT_MANIFEST)' '$(CLOUDMAKE_MANIFEST)'

_ssh-execute: _ssh-start
	@set -eu; \
	token="$$(cat '$(CLOUDMAKE_OWNER_ID_FILE)')-$$$$-$$(date +%s)"; \
	$(SSH) "mkdir -p '$(REMOTE_ROOT)' && sh -s -- acquire '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh'; \
	cleanup() { $(SSH) "sh -s -- release '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh' >/dev/null 2>&1 || :; }; \
	trap cleanup EXIT HUP INT TERM; \
	$(MAKE) --no-print-directory _ssh-sync-unlocked; \
	command="$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_make_command.py' \
		--source '$(REMOTE_SRC)' --makefile '$(REMOTE_MAKEFILE)' \
		--jobs '$(JOBS)' --target '$(REMOTE_TARGET)' \
		--target-b64 '$(REMOTE_TARGET_B64)' \
		--arguments-b64 '$(CLOUDMAKE_PROJECT_ARGS_B64)' )"; \
	$(SSH) "$$command"; \
	if test -n '$(REMOTE_COLLECT_DIR_B64)'; then \
		collect_command="$$( $(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_collect_command.py' \
			--source '$(REMOTE_SRC)' --directory-b64 '$(REMOTE_COLLECT_DIR_B64)' \
			--archive '$(REMOTE_ARTIFACT_ARCHIVE)' )"; \
		$(SSH) "$$collect_command"; \
	fi

.PHONY: _ssh-collect
_ssh-collect: _ssh-execute
	@$(MAKE) --no-print-directory _ssh-fetch

_ssh-fetch: _ssh-start
	@set -eu; \
	token="$$(cat '$(CLOUDMAKE_OWNER_ID_FILE)')-$$$$-$$(date +%s)"; \
	$(SSH) "mkdir -p '$(REMOTE_ROOT)' && sh -s -- acquire '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh'; \
	cleanup() { $(SSH) "sh -s -- release '$(REMOTE_LOCK)' '$$token' '$(REMOTE_LOCK_STALE)'" < '$(CLOUDMAKE_TOOL_ROOT)/tools/remote_lock.sh' >/dev/null 2>&1 || :; }; \
	trap cleanup EXIT HUP INT TERM; \
	mkdir -p '$(dir $(SSH_ARTIFACT_ARCHIVE))'; \
	$(RSYNC_BIN) -az -e '$(RSYNC_RSH)' \
		$(SSH_HOST):$(REMOTE_ARTIFACT_ARCHIVE) '$(SSH_ARTIFACT_ARCHIVE).tmp'; \
	mv '$(SSH_ARTIFACT_ARCHIVE).tmp' '$(SSH_ARTIFACT_ARCHIVE)'; \
	$(PYTHON_BIN) '$(CLOUDMAKE_TOOL_ROOT)/tools/safe_extract.py' \
		--archive '$(SSH_ARTIFACT_ARCHIVE)' --destination '$(ARTIFACT_DIR)'

_ssh-shell: _ssh-start
	$(SSH_BIN) -t $(SSH_OPTIONS) $(SSH_HOST) \
		'cd $(REMOTE_SRC) && exec bash -l'

_ssh-stop: ensure-owner
	$(BACKEND_STOP)
