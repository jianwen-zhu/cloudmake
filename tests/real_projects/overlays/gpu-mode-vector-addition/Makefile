CUDA_HOME ?= /usr/local/cuda
NVCC ?= $(CUDA_HOME)/bin/nvcc
NVCC_FLAGS ?= -O3 -I$(CUDA_HOME)/include
LD_FLAGS ?= -lcudart -L$(CUDA_HOME)/lib64

EXE := vector_addition
OBJ := vector_addition.o

.DEFAULT_GOAL := default

.PHONY: default run clean

default: $(EXE)

$(OBJ): vector_addition.cu
	$(NVCC) -c -o $@ $< $(NVCC_FLAGS)

$(EXE): $(OBJ)
	$(NVCC) $< -o $@ $(LD_FLAGS)

run: $(EXE)
	./$(EXE)

clean:
	rm -f $(OBJ) $(EXE)
