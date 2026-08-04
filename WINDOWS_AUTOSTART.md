# Windows Autostart

Unlike the Pi build, Windows development/testing usage typically doesn't
need autostart - but if you want the app to launch automatically when
you log in (e.g. running it on a dedicated reception-desk Windows PC),
here are two options.

## Option A: Startup folder shortcut (simplest)

1. Press `Win + R`, type `shell:startup`, press Enter - this opens your
   personal Startup folder.
2. Create a shortcut in that folder pointing to a small launcher batch
   file (see below), not directly to `python.exe`, so the working
   directory and venv activation are handled correctly.

Create `run_smart_attendance.bat` in the project root:
```bat
@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py
```

Then right-click that `.bat` file -> **Create shortcut**, and drag the
shortcut into the Startup folder from step 1.

## Option B: Task Scheduler (more control - delay, restart on failure)

1. Open **Task Scheduler** -> **Create Task** (not "Basic Task", so you
   get the full options).
2. **General** tab: name it "Smart Attendance System", check "Run
   whether user is logged on or not" if you want it to start before
   login (note: a GUI app run this way won't be visible on screen -
   only use this if you specifically want headless-style behavior,
   which doesn't really apply here since this app IS the GUI).
   For a normal desktop-visible launch, leave it as "Run only when user
   is logged on".
3. **Triggers** tab: New -> "At log on" -> your user account.
4. **Actions** tab: New -> Action: "Start a program" -> Program/script:
   the full path to `run_smart_attendance.bat` from Option A.
5. **Settings** tab: check "If the task fails, restart every" and set a
   reasonable interval (e.g. 1 minute, up to 3 attempts) - this gives
   you Windows-native equivalent of the Pi's systemd `Restart=on-failure`.

## Removing autostart

- Option A: delete the shortcut from `shell:startup`.
- Option B: Task Scheduler -> find "Smart Attendance System" -> Delete.
