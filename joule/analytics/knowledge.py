"""What a process is and what a person can actually do about it.

Helper processes are grouped into their app ('Google Chrome Helper (Renderer)' -> 'Google Chrome'), system
processes get advice that is feasible (you cannot quit WindowServer, but you can cut what it redraws), and
kernel processes are ignored.
"""
from __future__ import annotations

import re

IGNORE = {"kernel_task", "launchd", "idle", "logd", "powerd", "ps", "top", "ioreg", "powermetrics"}

APPS: list[tuple[str, str]] = [
    (r"^Google Chrome", "Google Chrome"),
    (r"^(Code Helper|Electron|Code$)", "Visual Studio Code"),
    (r"^Slack", "Slack"),
    (r"^(Microsoft Teams|MSTeams)", "Microsoft Teams"),
    (r"^(zoom\.us|ZoomWebviewHost|CptHost)", "Zoom"),
    (r"^Safari|^com\.apple\.WebKit", "Safari"),
    (r"^Spotify", "Spotify"),
    (r"^(Docker|com\.docker|qemu|vpnkit)", "Docker Desktop"),
    (r"^(Dropbox|OneDrive|Google Drive|bird|cloudd)", "cloud file sync"),
    (r"^(mds|mds_stores|mdworker|mdworker_shared|mdsync|corespotlightd)$", "Spotlight indexing"),
    (r"^(backupd|backupd-helper)$", "Time Machine"),
    (r"^(photoanalysisd|mediaanalysisd|photolibraryd)$", "Photos analysis"),
    (r"^WindowServer$", "WindowServer"),
    (r"^(ollama|ollama_llama_server)", "Ollama (local SLM)"),
]

ADVICE: dict[str, dict] = {
    "WindowServer": {
        "title": "Reduce screen redraw work (WindowServer)",
        "action": "Close or pause animated content (video tabs, moving wallpapers), lower brightness, and turn on "
                  "Reduce motion and Reduce transparency in Accessibility > Display.",
        "tradeoff": "less animation and a dimmer screen", "system": True},
    "Spotlight indexing": {
        "title": "Stop Spotlight re-indexing busy folders",
        "action": "Add build, dataset and node_modules folders to System Settings > Spotlight > Search Privacy.",
        "tradeoff": "files in those folders no longer appear in Spotlight search", "system": True},
    "Time Machine": {
        "title": "Run Time Machine backups while charging",
        "action": "Back up while plugged in instead of on battery (or back up less often).",
        "tradeoff": "backups are a little less frequent", "system": True},
    "Photos analysis": {
        "title": "Let Photos analysis run while charging",
        "action": "Keep Photos closed on battery; the analysis continues when the Mac is plugged in and idle.",
        "tradeoff": "new photos get searchable later", "system": True},
    "Visual Studio Code": {
        "title": "Trim idle VS Code work",
        "action": "Close unused VS Code windows and disable extensions you are not using (file watchers, linters "
                  "on huge folders).",
        "tradeoff": "fewer extensions running in the background", "system": False},
    "Google Chrome": {
        "title": "Put idle Chrome tabs to sleep",
        "action": "Close unused tabs and turn on Energy Saver and Memory Saver in Chrome settings > Performance.",
        "tradeoff": "sleeping tabs reload when you open them", "system": False},
    "cloud file sync": {
        "title": "Pause cloud file sync while idle",
        "action": "Pause syncing while you are not changing files, or sync only selected folders.",
        "tradeoff": "files reach the cloud later", "system": False},
    "Docker Desktop": {
        "title": "Stop Docker Desktop when you are not using containers",
        "action": "Quit Docker Desktop or enable Resource Saver mode when no containers are needed.",
        "tradeoff": "containers take a few seconds to start again", "system": False},
    "Ollama (local SLM)": {
        "title": "Unload the local model when idle",
        "action": "Set OLLAMA_KEEP_ALIVE to a short time so the model leaves memory when unused.",
        "tradeoff": "the first answer after a pause is slower", "system": False},
}


def app_of(process_name: str) -> str | None:
    """App or service a process belongs to; None for processes we ignore."""
    if process_name in IGNORE:
        return None
    for pattern, app in APPS:
        if re.search(pattern, process_name):
            return app
    return process_name


def advice_for(app: str) -> dict:
    return ADVICE.get(app, {
        "title": f"Reduce background activity of {app}",
        "action": f"Quit or pause '{app}' while you are not using it, or lower how often it refreshes.",
        "tradeoff": "the app may update or sync later than before", "system": False})
