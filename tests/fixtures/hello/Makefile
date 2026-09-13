BUILD_DIR ?= build
OUTPUT_DIR ?= output
CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -O2 -Wall -Wextra

PROGRAM := $(BUILD_DIR)/hello
SOURCES := $(wildcard src/*.c)
OBJECTS := $(patsubst src/%.c,$(BUILD_DIR)/%.o,$(SOURCES))

.PHONY: all build test run package clean

all: build

build: $(PROGRAM)

$(PROGRAM): $(OBJECTS)
	$(CC) $(CFLAGS) $^ -o $@

$(BUILD_DIR)/%.o: src/%.c
	@mkdir -p '$(@D)'
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

test: build
	@output=`$(PROGRAM)`; test "$$output" = 'remote build is working'

run: build
	$(PROGRAM)

package: build
	@mkdir -p '$(OUTPUT_DIR)'
	cp '$(PROGRAM)' '$(OUTPUT_DIR)/hello'

clean:
	$(RM) -r '$(BUILD_DIR)' '$(OUTPUT_DIR)'
