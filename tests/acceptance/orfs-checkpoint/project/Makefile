SHELL := /bin/sh

.PHONY: orfs-floorplan orfs-place clean

orfs-floorplan:
	@./orfs-acceptance.sh floorplan

orfs-place:
	@./orfs-acceptance.sh place

clean:
	@rm -rf .orfs-state evidence
