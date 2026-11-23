EMACS ?= emacs
EMACS_CONFIG ?= $(HOME)/.emacs.d
ELPA_TOOLS ?= $(abspath ../elpa)
PACKAGE_OUTPUT ?= $(CURDIR)/dist/packages
ELPA_PACKAGE_TOOL = uv run --project "$(ELPA_TOOLS)" --locked --managed-python "$(ELPA_TOOLS)/bin/packages.py"

.PHONY: package install-emacs check-emacs
package:
	@$(ELPA_PACKAGE_TOOL) build --source "$(CURDIR)" --output "$(PACKAGE_OUTPUT)" --emacs "$(EMACS)" $(if $(filter 1,$(DEV)),--dev)

install-emacs:
	@$(ELPA_PACKAGE_TOOL) install --source "$(CURDIR)" --config "$(EMACS_CONFIG)" --emacs "$(EMACS)" $(if $(filter 1,$(DEV)),--dev)

check-emacs:
	@$(ELPA_PACKAGE_TOOL) check --source "$(CURDIR)" --config "$(EMACS_CONFIG)" --emacs "$(EMACS)"
