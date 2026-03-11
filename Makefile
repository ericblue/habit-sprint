# habit-sprint Makefile
# Convenience targets for development, testing, and skill installation

.DEFAULT_GOAL := help

# ── Variables ──────────────────────────────────────────────────────────────────

PYTHON         = python3
VENV           = .venv
VENV_BIN       = $(VENV)/bin
PIP            = $(VENV_BIN)/pip
PYTEST         = $(VENV_BIN)/pytest
HABIT_SPRINT   = $(VENV_BIN)/habit-sprint

CLAUDE_SKILLS_DIR  = $(HOME)/.claude/skills
OPENCLAW_SKILLS_DIR ?= $(HOME)/clawd/skills

PORT           ?= 8000

SKILL_NAME     = habit-sprint
SKILL_SOURCE   = SKILLS.md
SKILL_TARGET   = SKILL.md

# ── Setup ──────────────────────────────────────────────────────────────────────

.PHONY: venv install install-global install-dev

venv: ## Create virtual environment (.venv/) if it doesn't exist
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
		echo "Virtual environment created at $(VENV)/"; \
	else \
		echo "Virtual environment already exists at $(VENV)/"; \
	fi

install: venv ## Install habit-sprint in editable mode
	$(PIP) install -e .
	@echo ""
	@echo "habit-sprint installed. Run with:"
	@echo "  $(HABIT_SPRINT) --help"

install-global: ## Install habit-sprint globally (adds habit-sprint to PATH)
	pip install -e .
	@echo ""
	@echo "habit-sprint installed globally. Verify with:"
	@echo "  which habit-sprint"
	@echo ""
	@echo "Database location: ~/.habit-sprint/habits.db"

install-dev: venv ## Install habit-sprint with dev dependencies (pytest)
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "habit-sprint installed with dev dependencies."

# ── CLI ────────────────────────────────────────────────────────────────────────

.PHONY: run run-example run-dashboard

run: ## Print usage examples for habit-sprint CLI
	@echo "habit-sprint CLI usage examples:"
	@echo ""
	@echo "  # List all sprints"
	@echo '  habit-sprint --json '"'"'{"action": "list_sprints"}'"'"''
	@echo ""
	@echo "  # Create a new sprint"
	@echo '  habit-sprint --json '"'"'{"action": "create_sprint", "payload": {"name": "March 2026", "start_date": "2026-03-01"}}'"'"''
	@echo ""
	@echo "  # Show sprint dashboard (markdown)"
	@echo '  habit-sprint --json '"'"'{"action": "sprint_dashboard"}'"'"' --format markdown'
	@echo ""
	@echo "  # Use a custom database"
	@echo '  habit-sprint --db /path/to/my.db --json '"'"'{"action": "list_sprints"}'"'"''
	@echo ""
	@echo "Run 'habit-sprint --help' for full CLI options."

run-example: ## Run a sample list_sprints action against a temp database
	@echo "Running list_sprints against a temporary database..."
	@$(HABIT_SPRINT) --db /tmp/habit-sprint-demo.db --json '{"action": "list_sprints"}'

run-dashboard: ## Run sprint_dashboard with markdown format (demo)
	@echo "Running sprint_dashboard (markdown format)..."
	@$(HABIT_SPRINT) --db /tmp/habit-sprint-demo.db --json '{"action": "sprint_dashboard"}' --format markdown

# ── Web Server ────────────────────────────────────────────────────────────────

.PHONY: serve install-web

install-web: venv ## Install habit-sprint with web dependencies (FastAPI, uvicorn, jinja2)
	$(PIP) install -e ".[web]"
	@echo ""
	@echo "habit-sprint installed with web dependencies."
	@echo "Run 'make serve' to start the web UI."

serve: ## Start the web UI server (use PORT=NNNN to change port, default 8000)
	$(HABIT_SPRINT) --web --port $(PORT)

# ── Testing ────────────────────────────────────────────────────────────────────

.PHONY: test

test: ## Run pytest
	$(PYTEST) -v

# ── Claude Code Skill Installation ────────────────────────────────────────────

.PHONY: claude-skill-install claude-skill-uninstall claude-skill-check

claude-skill-install: ## Install SKILLS.md as a Claude Code skill
	@if [ ! -f "$(SKILL_SOURCE)" ]; then \
		echo "Error: $(SKILL_SOURCE) not found in project root."; \
		exit 1; \
	fi
	@mkdir -p "$(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)"
	@cp "$(SKILL_SOURCE)" "$(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"
	@echo "Claude Code skill installed:"
	@echo "  $(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"
	@echo ""
	@echo "The skill is now available to Claude Code sessions."

claude-skill-uninstall: ## Remove habit-sprint skill from Claude Code
	@if [ -d "$(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)" ]; then \
		rm -rf "$(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)"; \
		echo "Claude Code skill uninstalled."; \
	else \
		echo "Claude Code skill not installed (nothing to remove)."; \
	fi

claude-skill-check: ## Show Claude Code skill install status
	@if [ -f "$(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)" ]; then \
		echo "Claude Code skill: INSTALLED"; \
		echo "  $(CLAUDE_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"; \
	else \
		echo "Claude Code skill: NOT INSTALLED"; \
		echo "  Run 'make claude-skill-install' to install."; \
	fi

# ── OpenClaw Skill Installation ───────────────────────────────────────────────

.PHONY: openclaw-skill-install openclaw-skill-uninstall openclaw-skill-check

openclaw-skill-install: ## Install SKILLS.md as an OpenClaw skill
	@if [ ! -f "$(SKILL_SOURCE)" ]; then \
		echo "Error: $(SKILL_SOURCE) not found in project root."; \
		exit 1; \
	fi
	@mkdir -p "$(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)"
	@cp "$(SKILL_SOURCE)" "$(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"
	@echo "OpenClaw skill installed:"
	@echo "  $(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"
	@echo ""
	@echo "The skill is now available to OpenClaw sessions."
	@echo "To use a custom skills directory: make openclaw-skill-install OPENCLAW_SKILLS_DIR=/path/to/skills"

openclaw-skill-uninstall: ## Remove habit-sprint skill from OpenClaw
	@if [ -d "$(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)" ]; then \
		rm -rf "$(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)"; \
		echo "OpenClaw skill uninstalled."; \
	else \
		echo "OpenClaw skill not installed (nothing to remove)."; \
	fi

openclaw-skill-check: ## Show OpenClaw skill install status
	@if [ -f "$(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)" ]; then \
		echo "OpenClaw skill: INSTALLED"; \
		echo "  $(OPENCLAW_SKILLS_DIR)/$(SKILL_NAME)/$(SKILL_TARGET)"; \
	else \
		echo "OpenClaw skill: NOT INSTALLED"; \
		echo "  Run 'make openclaw-skill-install' to install."; \
	fi

# ── Cleanup ────────────────────────────────────────────────────────────────────

.PHONY: clean clean-all

clean: ## Remove caches and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned caches and build artifacts."

clean-all: clean ## Clean + remove virtual environment
	rm -rf $(VENV)
	@echo "Removed virtual environment."

# ── Help ───────────────────────────────────────────────────────────────────────

.PHONY: help

help: ## Show available targets
	@echo "habit-sprint — available make targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Variables:"
	@echo "  PORT                 Web server port (default: 8000)"
	@echo "  OPENCLAW_SKILLS_DIR  Override OpenClaw skills directory (default: ~/clawd/skills)"
