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
VERSION := $(strip $(shell sed -n '1p' '$(CLOUDMAKE_TOOL_ROOT)/VERSION'))
CLOUDMAKE_RUNTIME_DIR ?= $(PREFIX)/libexec/cloudmake
DIST_DIR ?= $(CLOUDMAKE_TOOL_ROOT)/dist

CLOUDMAKE_RUNTIME_DIRS := backends core notebooks tools transports
CLOUDMAKE_RUNTIME_FILES := $(CLOUDMAKE_TOOL_ROOT)/Makefile $(CLOUDMAKE_TOOL_ROOT)/VERSION \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/backends/*.mk) \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/core/*.mk) \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/notebooks/*.ipynb) \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/tools/*.py) \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/tools/*.sh) \
	$(wildcard $(CLOUDMAKE_TOOL_ROOT)/transports/*.mk)

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

.PHONY: install dist
install:
	@mkdir -p '$(DESTDIR)$(PREFIX)/bin'
	@mkdir -p '$(DESTDIR)$(CLOUDMAKE_RUNTIME_DIR)'
	@for directory in $(CLOUDMAKE_RUNTIME_DIRS); do \
		mkdir -p '$(DESTDIR)$(CLOUDMAKE_RUNTIME_DIR)/'"$$directory"; \
	done
	@for file in $(CLOUDMAKE_RUNTIME_FILES); do \
		relative=$${file#'$(CLOUDMAKE_TOOL_ROOT)'/}; \
		install -m 644 "$$file" '$(DESTDIR)$(CLOUDMAKE_RUNTIME_DIR)/'"$$relative"; \
	done
	@install -m 755 '$(CLOUDMAKE_TOOL_ROOT)/bin/cloudmake' '$(DESTDIR)$(PREFIX)/bin/cloudmake'
	@echo 'Installed cloudmake $(VERSION) to $(DESTDIR)$(PREFIX)/bin/cloudmake'

dist:
	@mkdir -p '$(DIST_DIR)'
	@git -C '$(CLOUDMAKE_TOOL_ROOT)' archive \
		--format=tar --prefix='cloudmake-$(VERSION)/' HEAD | \
		gzip -n > '$(DIST_DIR)/cloudmake-$(VERSION).tar.gz'
	@if command -v sha256sum >/dev/null 2>&1; then \
		cd '$(DIST_DIR)' && sha256sum 'cloudmake-$(VERSION).tar.gz' > 'cloudmake-$(VERSION).tar.gz.sha256'; \
	else \
		cd '$(DIST_DIR)' && shasum -a 256 'cloudmake-$(VERSION).tar.gz' > 'cloudmake-$(VERSION).tar.gz.sha256'; \
	fi
	@echo 'Created $(DIST_DIR)/cloudmake-$(VERSION).tar.gz'
