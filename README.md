Prereqs:
- Windows 11
- Python 3.13
- rrrocket.exe (if you cannot download from here, please go to https://github.com/nickbabcock/rrrocket)
- A replay file (.replay)

First download the project or clone it and navigate to the project directory using this command in PowerShell or a VS code terminal:
 
  cd rocket-league-ai

Then, create a python virtual environment using these commands: 

  python -m venv .venv
  .\.venv\Scripts\Activate.ps1

If powershell prevents, run: 

  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

Then activate it again.
Now install the required Python packages using these commands:

  python -m pip install --upgrade pip
  pip install -r requirements.txt

Prepare your replay files under data/replays
Now you can run the program with:

   python process_replay.py

You should see the list of replays you've uploaded. You then select one by typing the numerical value of the replay in the list.

NOTE: This is experimental and still in progress. Detected mechanics are not guaranteed confirmations.
