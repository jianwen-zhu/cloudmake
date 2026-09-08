SHELL := /bin/sh

.PHONY: orfs-toolcheck orfs-floorplan orfs-place clean

orfs-toolcheck:
	+@./orfs-oci.sh toolcheck

orfs-floorplan:
	+@./orfs-oci.sh floorplan

orfs-place:
	+@./orfs-oci.sh place

clean:
	@rm -rf .orfs-state evidence
