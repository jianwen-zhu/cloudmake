CXX ?= g++
CUDA_HOME ?= /usr/local/cuda
NVCC ?= $(CUDA_HOME)/bin/nvcc

CPPFLAGS ?=
CXXFLAGS ?= -O3
NVCCFLAGS ?= -O3 -arch=native

SOURCE_DIR := Sources
BUILD_DIR ?= build

PROGRAMS := \
	$(BUILD_DIR)/cpu-cooling \
	$(BUILD_DIR)/gpu-cooling \
	$(BUILD_DIR)/thrust-cooling

.DEFAULT_GOAL := build

.PHONY: build run clean

build: $(PROGRAMS)

$(BUILD_DIR)/.directory:
	mkdir -p $(BUILD_DIR)
	touch $@

$(BUILD_DIR)/cpu-cooling: $(SOURCE_DIR)/cpu-cooling.cpp | $(BUILD_DIR)/.directory
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $< -o $@

$(BUILD_DIR)/gpu-cooling: $(SOURCE_DIR)/gpu-cooling.cpp | $(BUILD_DIR)/.directory
	$(NVCC) $(CPPFLAGS) $(NVCCFLAGS) -x cu $< -o $@

$(BUILD_DIR)/thrust-cooling: $(SOURCE_DIR)/thrust-cooling.cpp | $(BUILD_DIR)/.directory
	$(NVCC) $(CPPFLAGS) $(NVCCFLAGS) --extended-lambda -x cu $< -o $@

run: build
	@set -e; for program in $(PROGRAMS); do \
		echo "==> $$program"; \
		"$$program"; \
	done

clean:
	rm -rf $(BUILD_DIR)
