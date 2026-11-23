# Upload EZDuoboxing to GitHub

This folder is the repository root. Upload its CONTENTS so README.md appears at the root, not inside another EZDuoboxing directory. It contains scripts, examples, tests, documentation and GitHub workflow/templates. It does not include a GUI, executable, driver binaries, Python environment, personal configuration, or Git history.

## Repository details

Suggested repository name: **EZDuoboxing**

Suggested description:

> Script-based selective controller input forwarding for Steam Deck and Steam Controller MMORPG setups, with independent keyboard/mouse and gamepad mappings.

Suggested topics:

```text
steam-deck steam-controller steam-input python input-forwarding mmorpg gamepad windows
```

Do not advertise universal game compatibility or approval by a particular game/server. The README explains the limits.

## Before publishing

- Review the actual files being uploaded. The included configs contain placeholders; your working copies may not.
- Keep personal config files named `config.local.py` / `receiver.local.py`; .gitignore excludes `*.local.py`. Git ignore rules do not protect files manually uploaded through the browser or files already tracked by Git.
- Choose a license deliberately. If there is no LICENSE file, this package makes no open-source license grant. See LICENSING.md. Do not select a different license in GitHub without deciding how it should apply.
- Do not upload `.venv`, `__pycache__`, logs, credentials, drivers, or older unrelated bundles.

## Recommended: Git from the extracted directory

Create a new empty GitHub repository named EZDuoboxing in your account. Do not initialize it with a README/.gitignore/license because this folder already contains repository content. Choose public/private visibility as desired.

With Git installed, open a terminal in this folder:

```bash
git init
git branch -M main
git add .
git status --short
```

Review the staged filenames and `git diff --cached` before committing. Then:

```bash
git commit -m "Release EZDuoboxing script setup"
git remote add origin https://github.com/YOUR_USERNAME/EZDuoboxing.git
git push -u origin main
```

Replace YOUR_USERNAME; authenticate through your normal GitHub credential flow. Do not paste account access tokens into this project. If Git asks for author information, configure your chosen name/email (a GitHub no-reply address is an option), then retry the commit.

Once pushed, check the **Actions** tab for the Script tests workflow. The workflow runs simulated logic tests on Linux/Python 3.11 and 3.14. It does not validate Windows drivers or physical controllers. It is included but has not been run on your GitHub account before upload.

## Alternative: browser upload

Create/open the repository, choose **Add file → Upload files**, and upload the extracted contents, including `docs/`, `examples/`, `tests/` and `.github/`. Include `.gitignore` and `.gitattributes`; file pickers may hide dotfiles. Commit the upload. Verify README renders and the workflow file exists at `.github/workflows/tests.yml`.

Do not upload only the ZIP as repository source. A ZIP can be attached to a release, but GitHub cannot browse its internal source as repository files. [GitHub's upload guide](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).

## Create a release

After the source is committed and checked, create a GitHub release with tag `v4.9.1` and title `EZDuoboxing v4.9.1 — Script release`. Use the matching section of CHANGELOG.md as release notes. GitHub supplies a source archive from the tag; optionally attach the prepared ZIP and its SHA-256 checksum file.

Call out:

- Scripts only, no GUI/executable.
- Configurable physical selectors, including standard buttons.
- Deck native mode and Steam Input suppression setup.
- Optional Windows gamepad driver/package requirements.
- Hardware-validation limits and digital trigger output.

For future releases, update VERSION, startup labels and CHANGELOG together. Regenerate the distribution from reviewed source, never from a personal working folder containing secrets.
