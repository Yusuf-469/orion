"""Backend of the ORION interface: connects the window to the agent, voice, confirmations and the kill switch.

The window (HTML, see web/) calls these methods through pywebview's JS bridge; events go back with
evaluate_js. Everything that acts still goes through the tool runtime and policy engine: the interface
only shows what is happening and passes on the user's answers.
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any

from orion.config import OrionConfig
from orion.orchestration.cancel import CancelToken, KillSwitch, KillSwitchEngaged
from orion.policy.engine import ConfirmationRequest

log = logging.getLogger("orion.ui")

WEB_WORDS = re.compile(r"https?://|www\.|\.com|\bweb|site|page|search|google|compare|review|price|form|survey|"
                       r"job|apply|news|article|research|find|look up|online|browser|product", re.I)
DESK_WORDS = re.compile(r"calculat|paint|\bapp\b|window|desktop|notepad|open (the )?(calc|paint)", re.I)


def choose_tools(goal: str) -> list[str]:
    """Offer the model a focused tool set: small models choose much better from fewer tools (measured)."""
    from orion.tools.web import AGENT_TOOL_IDS
    files = ["files.list", "files.read", "docs.read_document", "docs.write_document"]
    if re.search(r"\bjobs?\b|\bcv\b|resume|résumé|career|vacanc|opening", goal, re.I):
        return ["jobs.shortlist", *AGENT_TOOL_IDS, *files]
    if re.search(r"\bcompar|\bvs\.?\b|versus|which (is|one) (is )?better|pros and cons", goal, re.I):
        return ["research.compare", *AGENT_TOOL_IDS, *files]
    desk = ["calculator.compute", "app.launch", "desktop.look", "desktop.click", "desktop.type", "desktop.keys"]
    if re.search(r"calculat|\bsum\b|percent|%|\bwork out\b", goal, re.I) and not WEB_WORDS.search(goal):
        # A verified tool exists: offer it alone. With generic clicking also on offer the model sometimes
        # pressed "=" repeatedly in the real Calculator (seen in the packaged app: 2400*0.15 -> 360 -> 54).
        return ["calculator.compute", *files]
    web, dsk = bool(WEB_WORDS.search(goal)), bool(DESK_WORDS.search(goal))
    if web and not dsk:
        return [*AGENT_TOOL_IDS, *files]
    if dsk and not web:
        return [*desk, *files]
    return [*AGENT_TOOL_IDS, *desk, *files]


class _Waiter:
    def __init__(self):
        self.event = threading.Event()
        self.value: Any = None


class Backend:
    def __init__(self, cfg: OrionConfig, llm_model: str = "qwen2.5:7b"):
        self.cfg = cfg
        self.window = None
        self.kill = KillSwitch()
        self.waiting: dict[str, _Waiter] = {}
        self.busy = threading.Lock()
        self.token: CancelToken | None = None
        self.profile_path = Path(cfg.data_dir) / "profile.json"
        self.history_path = Path(cfg.data_dir) / "agent_history.jsonl"
        self.settings_path = Path(cfg.data_dir) / "ui_settings.json"
        self.settings = {"voice": True, "ask_every_change": cfg.confirm_reversible, "model": llm_model,
                         "voice_id": "kokoro:af_heart", "voice_rate": 1.0}
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.settings.update({k: v for k, v in saved.items() if k in self.settings})
        except (OSError, ValueError):
            pass
        self._speaker = None
        self._recorder = None
        self._transcriber = None
        self._session = None
        self._runtime = None
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.workspace_dir).mkdir(parents=True, exist_ok=True)

    # --- plumbing ------------------------------------------------------------------------------
    def emit(self, event: dict[str, Any]) -> None:
        if self.window is not None:
            try:
                self.window.evaluate_js(f"window.orion && window.orion.onEvent({json.dumps(event, default=str)})")
            except Exception:  # noqa: BLE001 - the window may be closing
                pass

    def _voice(self):
        if self._speaker is None:
            from orion.voice import Speaker
            self._speaker = Speaker(self.settings["voice_id"], self.settings["voice_rate"])
        self._speaker.configure(self.settings["voice_id"], self.settings["voice_rate"])
        return self._speaker

    def say(self, text: str) -> None:
        if self.settings["voice"] and text:
            try:
                self._voice().say(text)
            except Exception:  # noqa: BLE001 - no audio device: stay silent
                pass

    def list_voices(self) -> list[dict[str, str]]:
        from orion.voice.speak import list_voices
        return list_voices()

    def preview_voice(self, voice_id: str, rate: float = 1.0) -> bool:
        """Say a short sample in the chosen voice (works even while voice output is switched off)."""
        try:
            sp = self._voice()
            sp.configure(voice_id, rate)
            name = self._profile().get("name", "").split(" ")[0]
            sp.say(f"Hi{' ' + name if name else ''}, I'm ORION. This is how I will sound when I talk to you.")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _build(self):
        if self._runtime is not None and self._runtime.policy.confirm_reversible == self.settings["ask_every_change"]:
            return self._runtime
        from orion.app.main_window import build_registry, install_demo_pages
        from orion.execution.runtime import ToolRuntime
        from orion.policy import PolicyEngine
        from orion.tools.desktop import desktop_tools
        from orion.tools.web import WebSession, web_tools
        from orion.models.ollama import OllamaBackend
        from orion.skills.compare import CompareTool
        from orion.skills.jobs import JobShortlistTool
        from orion.tools.web import DEFAULT_SEARCH
        from orion.tools.write_document import ReadDocumentTool, WriteDocumentTool
        install_demo_pages(Path(self.cfg.workspace_dir))
        if self._session is None:
            self._session = WebSession(Path(self.cfg.data_dir) / "browser_profile", headless=False)
        reg = build_registry()
        skill_llm = lambda: OllamaBackend(self.settings["model"], timeout_s=240, num_ctx=8192, num_predict=600)  # noqa: E731
        for t in [*web_tools(self._session), *desktop_tools(), WriteDocumentTool(), ReadDocumentTool(),
                  JobShortlistTool(self._session, skill_llm),
                  CompareTool(self._session, lambda: OllamaBackend(self.settings["model"], timeout_s=300,
                                                                   num_ctx=16384, num_predict=1500), DEFAULT_SEARCH)]:
            if t.spec.id not in reg:
                reg.register(t)
        perms = frozenset(self.cfg.granted_permissions)
        self._runtime = ToolRuntime(reg, PolicyEngine(perms, self.settings["ask_every_change"]), self,
                                    Path(self.cfg.workspace_dir))
        return self._runtime

    # Confirmer and Asker protocols (called from the task thread; they wait for the window) -------
    def _wait(self, kind: str, payload: dict[str, Any], token: CancelToken) -> Any:
        wid = uuid.uuid4().hex[:8]
        w = self.waiting[wid] = _Waiter()
        self.emit({"kind": kind, "id": wid, **payload})
        while not w.event.wait(0.1):
            if token.is_cancelled:
                self.emit({"kind": "dialog_closed", "id": wid})
                self.waiting.pop(wid, None)
                return None
        self.waiting.pop(wid, None)
        return w.value

    def confirm(self, req: ConfirmationRequest, token: CancelToken) -> bool:
        # Read the request aloud too, for people who cannot easily read or use the mouse.
        details = req.consequence.split("What is filled in:")[-1].replace("->", ",").replace("\n", ". ")[:600]
        self.say(f"{req.action} {details}. Say yes to approve, or no to cancel.")
        return bool(self._wait("confirm", {"action": req.action, "consequence": req.consequence,
                                           "tool": req.tool_id, "side_effect": str(req.side_effect)}, token))

    def choose(self, req: ConfirmationRequest, options: list[str], token: CancelToken) -> int | None:
        self.say(req.action)
        v = self._wait("choose", {"action": req.action, "consequence": req.consequence, "options": options}, token)
        return v if isinstance(v, int) else None

    def ask(self, question: str, token: CancelToken) -> str | None:
        self.say(question)
        v = self._wait("ask", {"question": question}, token)
        return v.strip() if isinstance(v, str) and v.strip() else None

    # --- API for the window (pywebview js_api) -------------------------------------------------
    def get_state(self) -> dict[str, Any]:
        prof = self._profile()
        hist = []
        if self.history_path.exists():
            for line in self.history_path.read_text(encoding="utf-8").splitlines()[-30:]:
                try:
                    hist.append(json.loads(line))
                except ValueError:
                    pass
        return {"profile": prof, "settings": self.settings, "history": hist[::-1],
                "workspace": str(Path(self.cfg.workspace_dir).resolve()), "hotkey": self.cfg.kill_hotkey}

    def _profile(self) -> dict[str, str]:
        try:
            return json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"name": "", "facts": ""}

    def save_profile(self, name: str, facts: str) -> bool:
        self.profile_path.write_text(json.dumps({"name": name.strip()[:80], "facts": facts.strip()[:8000]}),
                                     encoding="utf-8")
        return True

    def set_setting(self, key: str, value: Any) -> dict[str, Any]:
        if key in self.settings:
            self.settings[key] = value
            self.settings_path.write_text(json.dumps(self.settings), encoding="utf-8")
            if key in ("voice_id", "voice_rate") and self._speaker is not None:
                self._speaker.configure(self.settings["voice_id"], self.settings["voice_rate"])
        return self.settings

    def answer(self, wid: str, value: Any) -> bool:
        w = self.waiting.get(wid)
        if w is None:
            return False
        w.value = value
        w.event.set()
        return True

    def stop(self) -> bool:
        self.kill.engage("stopped by the user")
        if self._speaker is not None:
            self._speaker.stop()
        self.emit({"kind": "stopping"})
        return True

    def mic_start(self) -> bool:
        from orion.voice import Recorder
        if self._recorder is None:
            self._recorder = Recorder()
        self._recorder.start()
        self.emit({"kind": "listening"})
        return True

    def mic_stop(self) -> str:
        if self._recorder is None:
            return ""
        audio = self._recorder.stop()
        self.emit({"kind": "transcribing"})
        try:
            if self._transcriber is None:
                from orion.voice import Transcriber
                self._transcriber = Transcriber()
            text = self._transcriber.transcribe(audio)
        except Exception as e:  # noqa: BLE001
            self.emit({"kind": "error", "message": f"could not understand the audio: {e}"})
            return ""
        self.emit({"kind": "heard", "text": text})
        return text

    def run(self, goal: str) -> str:
        goal = goal.strip()
        if not goal:
            return ""
        if not self.busy.acquire(blocking=False):
            self.emit({"kind": "error", "message": "ORION is already working on a task. Press STOP to end it."})
            return ""
        if self.kill.engaged:
            self.kill.reset()
        tid = uuid.uuid4().hex[:8]
        threading.Thread(target=self._run, args=(tid, goal), name=f"task-{tid}", daemon=True).start()
        return tid

    def _run(self, tid: str, goal: str) -> None:
        t0 = time.monotonic()
        status, summary = "failed", ""
        try:
            try:
                self.token = self.kill.new_token()
            except KillSwitchEngaged:
                self.kill.reset()
                self.token = self.kill.new_token()
            self.emit({"kind": "task_start", "id": tid, "goal": goal})
            self.say("On it.")
            rt = self._build()
            status, summary = self._template(goal, rt) or self._agent(goal, rt)
        except Exception as e:  # noqa: BLE001
            log.exception("task failed")
            status, summary = "failed", f"Something went wrong: {type(e).__name__}: {e}"
        finally:
            secs = round(time.monotonic() - t0, 1)
            with self.history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": tid, "goal": goal, "status": status, "summary": summary[:1500],
                                    "seconds": secs, "when": time.strftime("%Y-%m-%d %H:%M")}) + "\n")
            if self.token is not None:
                self.kill.release(self.token)
            self.busy.release()   # free BEFORE announcing the end, so the next goal is accepted at once
            self.emit({"kind": "task_end", "id": tid, "status": status, "summary": summary, "seconds": secs})
            first = summary.split("\n")[0]
            self.say({"done": first, "cancelled": "Stopped."}.get(status, f"I could not finish. {first}"))

    def _template(self, goal: str, rt) -> tuple[str, str] | None:
        """Known phrases run through the deterministic planner: instant, validated, verified."""
        from orion.memory import TaskStore
        from orion.orchestration.graph_runner import GraphRunner
        from orion.planner.service import plan_request
        from orion.planner.template import TemplatePlanner
        from orion.recovery import RecoveryEngine
        from orion.verification import Verifier
        res = plan_request(TemplatePlanner(), goal, rt.registry, rt.policy, Path(self.cfg.workspace_dir))
        if res.status != "ok":
            return None
        self.emit({"kind": "plan", "source": "built-in planner", "plan": [s.description for s in res.plan.steps]})
        store = TaskStore(Path(self.cfg.data_dir) / "orion.db")
        try:
            def on_event(e):
                if e.get("kind") in ("step_started", "step_done", "step_failed", "step_blocked", "recovery"):
                    self.emit({"kind": "step", "text": e.get("message", ""), "ok": e["kind"] != "step_failed"})
            gr = GraphRunner(store, self.kill, rt, Verifier(Path(self.cfg.workspace_dir)), on_event=on_event,
                             recovery=RecoveryEngine(rt, self))
            task_id = gr.create(res.goal, res.plan, "template", False)
            outcome = gr.run(task_id, self.token, False)
            steps = store.list_steps(task_id)
            text = "; ".join(s["evidence"].split(" | ")[0] for s in steps if s.get("evidence"))[:600]
            status = {"verified_complete": "done", "cancelled": "cancelled"}.get(str(outcome), str(outcome))
            return status, f"{str(outcome).replace('_', ' ').capitalize()}. {text}"
        finally:
            store.close()

    def _agent(self, goal: str, rt) -> tuple[str, str]:
        from orion.agent import Agent
        from orion.models.ollama import OllamaBackend
        llm = OllamaBackend(self.settings["model"], timeout_s=240, num_ctx=16384, num_predict=1500)
        try:
            llm.health()
        except Exception as e:  # noqa: BLE001
            return "failed", (f"The local AI model is not available ({e}). Start Ollama (ollama serve) and make sure "
                              f"the model '{self.settings['model']}' is installed.")
        prof = self._profile()
        facts = "\n".join(x for x in (f"Name: {prof['name']}" if prof.get("name") else "", prof.get("facts", "")) if x)
        tools = choose_tools(goal)

        def on_event(e):
            if e["kind"] == "agent_plan":
                self.emit({"kind": "plan", "source": "AI planner", "plan": e.get("plan", [])})
            elif e["kind"] == "agent_step" and e.get("tool") not in ("finish",):
                self.emit({"kind": "thinking", "n": e["n"], "tool": e["tool"], "thought": e.get("thought", ""),
                           "args": _short_args(e.get("args", {}))})
            elif e["kind"] == "agent_result":
                self.emit({"kind": "step", "text": f"{e['tool']}: {e['evidence']}", "ok": e["ok"]})
            elif e["kind"] == "agent_selfcheck":
                self.emit({"kind": "step", "ok": not e["problems"],
                           "text": "Self-check: " + ("all answers match what you told me" if not e["problems"]
                                                     else "; ".join(e["problems"]))})
        agent = Agent(rt, llm, tools, asker=self, on_event=on_event, facts=facts, max_steps=40)
        res = agent.run(goal, self.token)
        return res.status, res.summary


def _short_args(args: dict[str, Any]) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "..."


class HotkeyThread(threading.Thread):
    """The global kill switch: a hotkey registered on its own thread (works whatever window is in front)."""

    def __init__(self, spec: str, on_press):
        super().__init__(name="orion-hotkey", daemon=True)
        self.spec, self.on_press = spec, on_press
        self.ok, self.message = False, ""
        self.ready = threading.Event()

    def run(self) -> None:
        from orion.app.hotkey import HOTKEY_ID, MOD_NOREPEAT, WM_HOTKEY, parse_hotkey
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            mods, vk = parse_hotkey(self.spec)
        except ValueError as e:
            self.message = str(e)
            self.ready.set()
            return
        self.ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk))
        self.message = (f"kill switch: {self.spec}" if self.ok else
                        f"could not register {self.spec} (another program uses it); use the STOP button")
        self.ready.set()
        msg = wintypes.MSG()
        while self.ok and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.on_press()
