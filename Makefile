ifndef CLOUDMAKE_TOOL_ROOT
CLOUDMAKE_TOOL_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
endif
PROJECT_DIR ?= $(CURDIR)
PROJECT ?= cloud-build-prototype
PROJECT_SLUG ?= $(PROJECT)
PROJECT_MAKEFILE ?= $(if $(filter $(abspath $(PROJECT_DIR)),$(CLOUDMAKE_TOOL_ROOT)),Makefile.build,Makefile)
ARTIFACT_DIR ?= $(abspath $(PROJECT_DIR))/artifacts
CLOUDMAKE_STATE_ROOT ?= .cloud-state
CLOUDMAKE_CACHE_ROOT ?= $(CLOUDMAKE_STATE_ROOT)/cache
BACKEND ?= colab-notebook
JOBS ?= 4
PREFIX ?= $(HOME)/.local

.DEFAULT_GOAL := help

BACKEND_FILE := $(CLOUDMAKE_TOOL_ROOT)/backends/$(BACKEND).mk

ifeq ($(wildcard $(BACKEND_FILE)),)
$(error Unknown backend "$(BACKEND)"; expected $(BACKEND_FILE))
endif

include $(BACKEND_FILE)
include $(CLOUDMAKE_TOOL_ROOT)/core/prerequisites.mk
include $(CLOUDMAKE_TOOL_ROOT)/core/resilience.mk

ifeq ($(BACKEND_TRANSPORT),colab-native)
include $(CLOUDMAKE_TOOL_ROOT)/transports/colab-native.mk
else ifeq ($(BACKEND_TRANSPORT),kaggle-kernel)
include $(CLOUDMAKE_TOOL_ROOT)/transports/kaggle-kernel.mk
else ifeq ($(BACKEND_TRANSPORT),ssh)
include $(CLOUDMAKE_TOOL_ROOT)/transports/ssh.mk
else
$(error Backend "$(BACKEND)" has unknown BACKEND_TRANSPORT "$(BACKEND_TRANSPORT)")
endif

.PHONY: install
install:
	@mkdir -p '$(DESTDIR)$(PREFIX)/bin'
	@install -m 755 '$(CLOUDMAKE_TOOL_ROOT)/bin/cloudmake' '$(DESTDIR)$(PREFIX)/bin/cloudmake'
	@echo 'Installed cloudmake to $(DESTDIR)$(PREFIX)/bin/cloudmake'
