# GitHub Release Checklist

Before publishing:

- [ ] Replace `your-email@example.com` in `ros/baxter_chess/package.xml`.
- [ ] Add your YouTube link in `README.md` and `docs/DEMO.md`.
- [ ] Confirm no private calibration files are committed.
- [ ] Confirm no `.env`, captures, videos, or generated cache files are committed unless intended.
- [ ] Run `python3 -m py_compile` on the Python files.
- [ ] Test the controller in dry-run mode.
- [ ] Test `rosrun baxter_chess test_square.py` before running real moves.

Suggested first commit:

```bash
git init
git add .
git commit -m "Initial Baxter chess robot repository"
git branch -M main
git remote add origin https://github.com/<your-username>/baxter-chess-robot.git
git push -u origin main
```
