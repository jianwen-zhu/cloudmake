.PHONY: verify

verify:
	@printf 'kernel=%s\n' "$$(uname -s)"
	@printf 'arch=%s\n' "$$(uname -m)"
	@printf 'make=%s\n' "$$(make --version | sed -n '1p')"
	@test -f /workspace/Makefile
	@printf 'workspace=ok\n'
