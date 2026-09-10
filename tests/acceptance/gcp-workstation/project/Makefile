.PHONY: verify increment outbound serve-once gpu-smoke export-artifact

verify:
	@test -f build/count
	@printf 'persistent-count=%s\n' "$$(cat build/count)"

increment:
	@mkdir -p build
	@n=$$(cat build/count 2>/dev/null || echo 0); n=$$((n + 1)); \
		printf '%s\n' "$$n" > build/count; \
		printf 'persistent-count=%s\n' "$$n"

outbound:
	@python3 -c 'import urllib.request; print("outbound-status=" + str(urllib.request.urlopen("https://www.google.com/generate_204", timeout=10).status))'

serve-once:
	@python3 server.py 18080

gpu-smoke:
	@nvidia-smi --query-gpu=name,driver_version --format=csv,noheader

export-artifact:
	@mkdir -p dist
	@cp build/count dist/count.txt
