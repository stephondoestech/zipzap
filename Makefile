# ZipZap Makefile

PYTHON := python3
SCRIPT := zipzap.py

.PHONY: help install install-tkinter test clean run gui demo

help: ## Show this help message
	@echo "ZipZap - Recursive Zip File Extractor"
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Make the script executable and install dependencies
	chmod +x $(SCRIPT)
	@echo "Script made executable"
	@echo "Checking for tkinter (GUI support)..."
	@$(PYTHON) -c "import tkinter" 2>/dev/null || $(MAKE) install-tkinter
	@echo "Installation completed"

install-tkinter: ## Install tkinter if missing
	@echo "tkinter not found, attempting to install..."
	@PYTHON_VERSION=$$($(PYTHON) --version | cut -d' ' -f2 | cut -d'.' -f1,2); \
	echo "Detected Python version: $$PYTHON_VERSION"; \
	if command -v brew >/dev/null 2>&1; then \
		echo "Installing python-tk@$$PYTHON_VERSION via Homebrew..."; \
		if [ "$$PYTHON_VERSION" = "3.10" ]; then \
			brew install python-tk@3.10 || echo "python-tk@3.10 not available, trying generic python-tk"; \
			brew install python-tk || echo "Failed to install python-tk"; \
		elif [ "$$PYTHON_VERSION" = "3.11" ]; then \
			brew install python-tk@3.11 || echo "python-tk@3.11 not available, trying generic python-tk"; \
			brew install python-tk || echo "Failed to install python-tk"; \
		elif [ "$$PYTHON_VERSION" = "3.12" ]; then \
			brew install python-tk@3.12 || echo "python-tk@3.12 not available, trying generic python-tk"; \
			brew install python-tk || echo "Failed to install python-tk"; \
		elif [ "$$PYTHON_VERSION" = "3.13" ]; then \
			brew install python-tk@3.13 || echo "python-tk@3.13 not available, trying generic python-tk"; \
			brew install python-tk || echo "Failed to install python-tk"; \
		else \
			brew install python-tk || echo "Failed to install python-tk"; \
		fi; \
	elif command -v apt-get >/dev/null 2>&1; then \
		echo "Installing python3-tk via apt..."; \
		sudo apt-get update && sudo apt-get install -y python3-tk || echo "Failed to install via apt"; \
	elif command -v yum >/dev/null 2>&1; then \
		echo "Installing tkinter via yum..."; \
		sudo yum install -y tkinter || echo "Failed to install via yum"; \
	elif command -v dnf >/dev/null 2>&1; then \
		echo "Installing python3-tkinter via dnf..."; \
		sudo dnf install -y python3-tkinter || echo "Failed to install via dnf"; \
	elif command -v pacman >/dev/null 2>&1; then \
		echo "Installing tk via pacman..."; \
		sudo pacman -S tk || echo "Failed to install via pacman"; \
	else \
		echo "Package manager not found. Please install tkinter manually:"; \
		echo "  macOS: brew install python-tk@$$PYTHON_VERSION (or python-tk)"; \
		echo "  Ubuntu/Debian: sudo apt-get install python3-tk"; \
		echo "  RHEL/CentOS: sudo yum install tkinter"; \
		echo "  Fedora: sudo dnf install python3-tkinter"; \
		echo "  Arch: sudo pacman -S tk"; \
	fi; \
	echo "After installation, you may need to restart your terminal or source your shell profile."

test: ## Run basic functionality test
	@echo "Creating test directory with zip files..."
	@mkdir -p /tmp/zipzap_test
	@cd /tmp/zipzap_test && \
		echo "test content 1" > file1.txt && \
		echo "test content 2" > file2.txt && \
		zip -q test1.zip file1.txt && \
		zip -q test2.zip file2.txt && \
		rm file1.txt file2.txt
	@echo "Running ZipZap on test directory..."
	@$(PYTHON) $(SCRIPT) /tmp/zipzap_test
	@echo "Test completed. Extracted files:"
	@ls -la /tmp/zipzap_test/
	@echo "Cleaning up test directory..."
	@rm -rf /tmp/zipzap_test

clean: ## Clean up generated files
	@echo "Cleaning up generated files..."
	@rm -f zipzap_progress.json
	@rm -f zipzap.log
	@echo "Cleanup completed"

run: ## Run with command line interface (requires directory argument)
	@if [ -z "$(DIR)" ]; then \
		echo "Usage: make run DIR=/path/to/directory"; \
		echo "Example: make run DIR=/Users/username/Downloads"; \
		exit 1; \
	fi
	@echo "Running ZipZap on directory: $(DIR)"
	@$(PYTHON) $(SCRIPT) "$(DIR)"

gui: ## Launch GUI interface
	@echo "Checking for GUI support..."
	@$(PYTHON) -c "import tkinter" 2>/dev/null || $(MAKE) install-tkinter
	@echo "Launching ZipZap GUI..."
	@$(PYTHON) $(SCRIPT) --gui

demo: ## Create demo directory with sample zip files
	@echo "Creating demo directory with sample zip files..."
	@mkdir -p zipzap_demo/subdir
	@cd zipzap_demo && \
		echo "This is a demo file" > demo1.txt && \
		echo "Another demo file" > demo2.txt && \
		echo "Subdirectory file" > subdir/demo3.txt && \
		zip -q demo1.zip demo1.txt && \
		zip -q demo2.zip demo2.txt && \
		cd subdir && zip -q demo3.zip demo3.txt && \
		cd .. && rm demo1.txt demo2.txt subdir/demo3.txt
	@echo "Demo directory created: zipzap_demo/"
	@echo "Contents:"
	@find zipzap_demo -name "*.zip" | sort
	@echo ""
	@echo "To test: make run DIR=zipzap_demo"
	@echo "To clean: rm -rf zipzap_demo"

check: ## Check if Python and dependencies are available
	@echo "Checking Python installation..."
	@$(PYTHON) --version
	@echo "Checking script syntax..."
	@$(PYTHON) -m py_compile $(SCRIPT)
	@echo "Checking for tkinter (GUI support)..."
	@$(PYTHON) -c "import tkinter; print('GUI support: Available')" 2>/dev/null || echo "GUI support: Not available (tkinter missing)"
	@echo "All checks passed!"

info: ## Show application info
	@echo "ZipZap - Recursive Zip File Extractor"
	@echo "======================================"
	@echo "Script: $(SCRIPT)"
	@echo "Python: $(PYTHON)"
	@echo ""
	@echo "Features:"
	@echo "  • Recursive directory scanning"
	@echo "  • Resumable operations"
	@echo "  • Progress tracking"
	@echo "  • GUI interface (when available)"
	@echo "  • Comprehensive logging"
	@echo ""
	@echo "Usage:"
	@echo "  Command line: $(PYTHON) $(SCRIPT) /path/to/directory"
	@echo "  GUI mode:     $(PYTHON) $(SCRIPT) --gui"