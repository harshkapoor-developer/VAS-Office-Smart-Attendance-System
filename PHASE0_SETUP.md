# Phase 0 — Environment Setup (Windows)

## Why this phase exists
`face_recognition` depends on `dlib`, and `dlib` ships **no prebuilt wheels on PyPI** — I checked directly against the package index. That means `pip install dlib` always compiles C++ code on your machine, for every Python version. If you skip the steps below, the install will fail partway through with a confusing CMake or MSVC error, not a friendly message.

## Step 1 — Install CMake
1. Download the Windows installer: https://cmake.org/download/
2. During install, check **"Add CMake to the system PATH for all users."**
3. Verify: open a new terminal and run `cmake --version`

## Step 2 — Install Visual Studio Build Tools (C++ compiler)
1. Download: https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. In the installer, select the **"Desktop development with C++"** workload
3. This installs the MSVC compiler `dlib`'s build step needs. You do not need full Visual Studio, just Build Tools.

## Step 3 — Create a virtual environment
```powershell
cd smart_attendance_system
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
```

## Step 4 — Install dependencies
```powershell
pip install -r requirements.txt
```
This step will take several minutes the first time — `dlib` is compiling from source, not downloading a wheel. That's expected, not a hang.

**If this fails on Python 3.14.6:** dlib's build has been most widely tested on 3.11/3.12. Rather than debug a brand-new interpreter's compiler quirks, install Python 3.11 or 3.12 side by side (they can coexist with 3.14), recreate the venv with `py -3.12 -m venv venv`, and retry. Everything else in this project is version-agnostic — this is purely about giving dlib's build a well-trodden path.

## Step 5 — Run the validator
```powershell
python validate_environment.py
```
Expected: every line reads `[PASS]`, aside from the informational `[WARN]` about Python 3.14 if you're on it and it worked anyway. If anything reads `[FAIL]`, fix that item and re-run — don't move to Phase 1 with failures outstanding.

## What "done" looks like for Phase 0
- [ ] `cmake --version` works in your terminal
- [ ] Build Tools installed with the C++ workload
- [ ] `venv` created and activated
- [ ] `pip install -r requirements.txt` completes with no errors
- [ ] `python validate_environment.py` reports 0 failures, including a real webcam frame capture

Once all boxes are checked, tell me and I'll start Phase 1 (project skeleton, config, and folder auto-creation).
