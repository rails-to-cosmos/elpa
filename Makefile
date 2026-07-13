.PHONY: build update publish serve clean squash-history force-push

MSG ?= History squashed

build: ## Build the archive into docs/
	eask install-deps --dev
	eask exec emacs --batch -l build.el

update: ## Re-fetch latest commits for every recipe and rebuild
	rm -rf .working
	$(MAKE) build

publish: build ## Build, then commit docs/ and push to GitHub Pages
	git add docs
	git commit -m "Update ELPA archive"
	git push

serve: build ## Build, then serve locally at http://localhost:8080
	cd docs && python3 -m http.server 8080

clean: ## Remove build output
	rm -rf docs .working

squash-history: ## Collapse ALL history into one commit (MSG="first commit"); force-push manually after
	git checkout --orphan _squash_tmp
	git add -A
	git commit -m "$(MSG)"
	git branch -D main
	git branch -m main
	@echo "Done. History collapsed to single commit on 'main'."
	@echo "Push with: make force-push"

force-push: ## Force-push local main over remote history (--force-with-lease)
	git push --force-with-lease origin main
