.PHONY: verify increment serve export-artifact

verify:
	@test "$${CLOUDMAKE_PROFILE:-}" = portable
	@test "$$(id -u)" -ne 0
	@printf 'portable Dev Container uid=%s\n' "$$(id -u)"

increment: verify
	@count=$$(( $$(cat .workstation-count 2>/dev/null || printf 0) + 1 )); \
		printf '%s\n' "$$count" > .workstation-count; \
		printf 'workstation count=%s\n' "$$count"

serve: verify
	@python3 serve_once.py "$(PORT)" "$(TOKEN)"

export-artifact: verify
	@mkdir -p dist
	@printf 'devcontainer-ssh-ok\n' > dist/result.txt
