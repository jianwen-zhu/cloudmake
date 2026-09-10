PORT ?= 18080
TOKEN ?= cloudmake-codespaces-inbound-ok
STATE_DIR ?= /tmp/cloudmake-codespaces-inbound

.PHONY: serve stop-server

serve:
	@set -eu; \
	case '$(PORT)' in ''|*[!0-9]*) echo 'PORT must be numeric' >&2; exit 2;; esac; \
	mkdir -p '$(STATE_DIR)'; \
	if test -f '$(STATE_DIR)/server.pid'; then \
		kill "$$(cat '$(STATE_DIR)/server.pid')" >/dev/null 2>&1 || :; \
	fi; \
	printf '%s\n' '$(TOKEN)' > '$(STATE_DIR)/index.html'; \
	nohup python3 -m http.server '$(PORT)' --bind 127.0.0.1 \
		--directory '$(STATE_DIR)' > '$(STATE_DIR)/server.log' 2>&1 < /dev/null & \
	pid=$$!; \
	printf '%s\n' "$$pid" > '$(STATE_DIR)/server.pid'; \
	sleep 1; \
	kill -0 "$$pid"; \
	printf '[cloudmake-test] inbound-listener=ready port=%s\n' '$(PORT)'

stop-server:
	@set -eu; \
	if test -f '$(STATE_DIR)/server.pid'; then \
		kill "$$(cat '$(STATE_DIR)/server.pid')" >/dev/null 2>&1 || :; \
		rm -f '$(STATE_DIR)/server.pid'; \
	fi; \
	printf '[cloudmake-test] inbound-listener=stopped port=%s\n' '$(PORT)'
