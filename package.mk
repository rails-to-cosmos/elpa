EMACS ?= emacs
EMACS_CONFIG ?= $(HOME)/.emacs.d
ELPA_TOOLS ?= $(abspath ../elpa)
PACKAGE_OUTPUT ?= $(CURDIR)/dist/packages

.PHONY: package install-emacs check-emacs
package:
	@python3 "$(ELPA_TOOLS)/bin/packages.py" build --source "$(CURDIR)" --output "$(PACKAGE_OUTPUT)" --emacs "$(EMACS)" $(if $(filter 1,$(DEV)),--dev)

install-emacs:
	@python3 "$(ELPA_TOOLS)/bin/packages.py" install --source "$(CURDIR)" --config "$(EMACS_CONFIG)" --emacs "$(EMACS)" $(if $(filter 1,$(DEV)),--dev)

check-emacs:
	@python3 "$(ELPA_TOOLS)/bin/packages.py" check --source "$(CURDIR)" --config "$(EMACS_CONFIG)" --emacs "$(EMACS)"
