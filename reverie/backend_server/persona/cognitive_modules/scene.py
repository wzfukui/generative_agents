import datetime
import os
import random
from dataclasses import dataclass

from text_sanitize import world_sanitize

SEED_EMBEDDING_DIM = 1536

SCENE_LOC_ALIAS = {
  "Isabella Rodriguez's apartment": "怡红院",
  "Dorm for Oak Hill College": "潇湘馆",
  "The Rose and Crown Pub": "蘅芜苑",
  "Johnson Park": "沁芳亭",
  "Hobbs Cafe": "正厅",
}

SCENE_CONFIG = {
  "cooldown_minutes": int(os.getenv("SCENE_COOLDOWN_MINUTES", "90")),
  "pair_cooldown_minutes": int(os.getenv("SCENE_PAIR_COOLDOWN_MINUTES", "50")),
  "queue_min_delay": int(os.getenv("SCENE_QUEUE_MIN_DELAY", "10")),
  "queue_max_delay": int(os.getenv("SCENE_QUEUE_MAX_DELAY", "30")),
  "prob_visit": float(os.getenv("SCENE_PROB_VISIT", "0.5")),
  "prob_poetry": float(os.getenv("SCENE_PROB_POETRY", "0.6")),
  "prob_meal": float(os.getenv("SCENE_PROB_MEAL", "0.55")),
  "prob_night": float(os.getenv("SCENE_PROB_NIGHT", "0.6")),
}

SCENE_WINDOWS = {
  "探病": [(7, 18)],
  "诗社": [(12, 18)],
  "家宴": [(11, 14), (17, 20)],
  "夜谈": [(20, 24), (0, 5)],
}


@dataclass
class SceneEvent:
  scene_type: str
  location: str
  participants: list
  summary: str
  timestamp: str

  def to_memory_description(self):
    people = ",".join(self.participants)
    return (
      f"【场景】type={self.scene_type}"
      f"｜loc={self.location}"
      f"｜with={people}"
      f"｜summary={self.summary}"
      f"｜ts={self.timestamp}"
    )


def _seed_embedding(seed_text):
  rng = random.Random(hash(seed_text))
  return [rng.random() for _ in range(SEED_EMBEDDING_DIM)]


def _scene_cooldown_ok(persona, scene_type, minutes=90):
  if not hasattr(persona.scratch, "scene_cooldowns"):
    persona.scratch.scene_cooldowns = {}
  last_seen = persona.scratch.scene_cooldowns.get(scene_type)
  if not last_seen:
    return True
  delta = persona.scratch.curr_time - last_seen
  return delta.total_seconds() >= minutes * 60


def _set_scene_cooldown(persona, scene_type):
  if not hasattr(persona.scratch, "scene_cooldowns"):
    persona.scratch.scene_cooldowns = {}
  persona.scratch.scene_cooldowns[scene_type] = persona.scratch.curr_time


def _scene_last_seen(persona, scene_type):
  if not hasattr(persona.scratch, "scene_cooldowns"):
    persona.scratch.scene_cooldowns = {}
  return persona.scratch.scene_cooldowns.get(scene_type)


def _pair_cooldown_ok(persona, other_name, scene_type, minutes=50):
  if not hasattr(persona.scratch, "scene_pair_cooldowns"):
    persona.scratch.scene_pair_cooldowns = {}
  key = f"{scene_type}:{other_name}"
  last_seen = persona.scratch.scene_pair_cooldowns.get(key)
  if not last_seen:
    return True
  delta = persona.scratch.curr_time - last_seen
  return delta.total_seconds() >= minutes * 60


def _set_pair_cooldown(persona, other_name, scene_type):
  if not hasattr(persona.scratch, "scene_pair_cooldowns"):
    persona.scratch.scene_pair_cooldowns = {}
  key = f"{scene_type}:{other_name}"
  persona.scratch.scene_pair_cooldowns[key] = persona.scratch.curr_time


def _in_window(hour, windows):
  for start, end in windows:
    if start <= end and start <= hour <= end:
      return True
    if start > end and (hour >= start or hour <= end):
      return True
  return False


def _get_scene_queue(persona):
  if not hasattr(persona.scratch, "scene_queue"):
    persona.scratch.scene_queue = []
  return persona.scratch.scene_queue


def _queue_scene(persona, item):
  queue = _get_scene_queue(persona)
  queue.append(item)


def _pop_ready_scene(init_persona, target_persona, now):
  queue = _get_scene_queue(init_persona)
  ready = []
  for item in queue:
    if now < item["ready_at"]:
      continue
    if target_persona.name not in item["participants"]:
      continue
    ready.append(item)
  if not ready:
    return None
  chosen = random.choice(ready)
  queue.remove(chosen)
  _remove_scene_from_queue(target_persona, chosen)
  return chosen


def _remove_scene_from_queue(persona, item):
  queue = _get_scene_queue(persona)
  queue[:] = [
    q for q in queue
    if not (q["scene_type"] == item["scene_type"]
            and q["participants"] == item["participants"]
            and q["ready_at"] == item["ready_at"])
  ]


def add_scene_memory(persona, scene_event):
  description = world_sanitize(scene_event.to_memory_description())
  keywords = [
    "场景",
    scene_event.scene_type,
    scene_event.location,
  ] + scene_event.participants
  embedding_pair = (description, _seed_embedding(description))
  return persona.a_mem.add_event(
    persona.scratch.curr_time,
    None,
    persona.name,
    "experience",
    "scene",
    description,
    keywords,
    3,
    embedding_pair,
    None,
  )


def maybe_trigger_scene(init_persona, target_persona, curr_loc, convo_summary):
  if not init_persona.scratch.curr_time:
    return None
  now = init_persona.scratch.curr_time
  hour = now.hour
  loc = SCENE_LOC_ALIAS.get(curr_loc, curr_loc)
  participants = [init_persona.name, target_persona.name]
  summary_text = convo_summary or ""
  queued = _pop_ready_scene(init_persona, target_persona, now)
  if queued:
    if _scene_cooldown_ok(init_persona, queued["scene_type"], SCENE_CONFIG["cooldown_minutes"]):
      if _pair_cooldown_ok(init_persona, target_persona.name,
                           queued["scene_type"], SCENE_CONFIG["pair_cooldown_minutes"]):
        summary = world_sanitize(queued["summary"])
        event = SceneEvent(
          queued["scene_type"],
          queued["location"],
          participants,
          summary,
          now.strftime("%Y-%m-%d %H:%M:%S"),
        )
        _set_scene_cooldown(init_persona, queued["scene_type"])
        _set_scene_cooldown(target_persona, queued["scene_type"])
        _set_pair_cooldown(init_persona, target_persona.name, queued["scene_type"])
        _set_pair_cooldown(target_persona, init_persona.name, queued["scene_type"])
        return event

  candidates = []
  if (_in_window(hour, SCENE_WINDOWS["探病"])
      and any("黛玉" in p for p in participants)
      and (any(word in summary_text for word in ["咳", "病", "体弱"])
           or random.random() < SCENE_CONFIG["prob_visit"])):
    candidates.append(("探病", "潇湘馆", SCENE_CONFIG["prob_visit"], "在潇湘馆探望身体不适之人"))
  if (_in_window(hour, SCENE_WINDOWS["诗社"])
      and (any(word in summary_text for word in ["诗", "吟", "诗话", "联句"])
           or random.random() < SCENE_CONFIG["prob_poetry"])):
    poetry_loc = "沁芳亭" if loc == "沁芳亭" else "回廊"
    candidates.append(("诗社", poetry_loc, SCENE_CONFIG["prob_poetry"], f"在{poetry_loc}吟诗联句"))
  if _in_window(hour, SCENE_WINDOWS["家宴"]):
    candidates.append(("家宴", "正厅", SCENE_CONFIG["prob_meal"], "在正厅小聚用膳"))
  if (_in_window(hour, SCENE_WINDOWS["夜谈"])
      and "宝玉" in "".join(participants)
      and any("黛玉" in p or "宝钗" in p for p in participants)
      and random.random() < SCENE_CONFIG["prob_night"]):
    candidates.append(("夜谈", "怡红院", SCENE_CONFIG["prob_night"], "夜里在怡红院低声交谈"))

  eligible = []
  for scene_type, location, prob, summary in candidates:
    if not _scene_cooldown_ok(init_persona, scene_type, SCENE_CONFIG["cooldown_minutes"]):
      continue
    if not _pair_cooldown_ok(init_persona, target_persona.name,
                             scene_type, SCENE_CONFIG["pair_cooldown_minutes"]):
      continue
    eligible.append((scene_type, location, prob, summary))

  if not eligible:
    return None

  picked = []
  for scene_type, location, prob, summary in eligible:
    if random.random() <= prob:
      picked.append((scene_type, location, prob, summary))

  if not picked:
    picked = [max(eligible, key=lambda item: item[2])]

  chosen = random.choice(picked)
  for item in eligible:
    if item == chosen:
      continue
    delay = random.randint(SCENE_CONFIG["queue_min_delay"], SCENE_CONFIG["queue_max_delay"])
    ready_at = now + datetime.timedelta(minutes=delay)
    queued_item = {
      "scene_type": item[0],
      "location": item[1],
      "summary": item[3],
      "participants": participants,
      "ready_at": ready_at,
    }
    _queue_scene(init_persona, queued_item)
    _queue_scene(target_persona, queued_item)

  scene_type, location, prob, summary = chosen
  summary = world_sanitize(summary)
  event = SceneEvent(scene_type, location, participants, summary,
                     now.strftime("%Y-%m-%d %H:%M:%S"))
  _set_scene_cooldown(init_persona, scene_type)
  _set_scene_cooldown(target_persona, scene_type)
  _set_pair_cooldown(init_persona, target_persona.name, scene_type)
  _set_pair_cooldown(target_persona, init_persona.name, scene_type)
  return event
