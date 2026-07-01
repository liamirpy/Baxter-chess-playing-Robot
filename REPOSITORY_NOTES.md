# Repository Notes

This repository was cleaned and organized from an uploaded Baxter chess package.

Changes made during packaging:

- Removed macOS metadata and Python bytecode cache files.
- Split the project into `controller/`, `ros/baxter_chess/`, `scripts/`, and `docs/`.
- Added a top-level README, license, `.gitignore`, setup docs, troubleshooting docs, and GitHub Actions syntax check.
- Updated the ROS `CMakeLists.txt` so `calibrate_home.py` and `go_home.py` are installed.
- Added `controller/baxter_status_bridge.py` and kept `baxter_keyboard_bridge.py` as a wrapper for compatibility.
- Replaced local machine paths in documentation with generic placeholders.

Remaining TODOs before publishing:

- Add the YouTube demo URL.
- Replace `your-email@example.com` in `ros/baxter_chess/package.xml` if you want public maintainer metadata.
- Test on the actual Baxter/Kinect hardware before tagging a release.
