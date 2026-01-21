import datetime
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

  candidates = []
  if 7 <= hour <= 18 and any("黛玉" in p for p in participants):
    if any(word in summary_text for word in ["咳", "病", "体弱"]) or random.random() < 0.6:
      candidates.append(("探病", "潇湘馆", 0.9, "在潇湘馆探望身体不适之人"))
  if 7 <= hour <= 20:
    if any(word in summary_text for word in ["诗", "吟", "诗话", "联句"]) or random.random() < 0.7:
      poetry_loc = "沁芳亭" if loc == "沁芳亭" else "回廊"
      candidates.append(("诗社", poetry_loc, 0.98, f"在{poetry_loc}吟诗联句"))
  if 7 <= hour <= 20:
    candidates.append(("家宴", "正厅", 0.98, "在正厅小聚用膳"))
  if hour >= 19 or hour <= 5:
    if "宝玉" in "".join(participants) and any("黛玉" in p or "宝钗" in p for p in participants):
      candidates.append(("夜谈", "怡红院", 0.98, "夜里在怡红院低声交谈"))

  eligible = []
  for scene_type, location, prob, summary in candidates:
    if not _scene_cooldown_ok(init_persona, scene_type):
      continue
    eligible.append((scene_type, location, prob, summary))

  if not eligible:
    return []

  def _score(item):
    scene_type, location, prob, summary = item
    last_seen = _scene_last_seen(init_persona, scene_type)
    if not last_seen:
      return 1e9
    delta = now - last_seen
    return delta.total_seconds()

  if len(eligible) >= 2:
    selected = sorted(eligible, key=_score, reverse=True)[:2]
  else:
    selected = [max(eligible, key=_score)]
  events = []
  timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
  for scene_type, location, prob, summary in selected:
    summary = world_sanitize(summary)
    event = SceneEvent(scene_type, location, participants, summary, timestamp)
    _set_scene_cooldown(init_persona, scene_type)
    _set_scene_cooldown(target_persona, scene_type)
    events.append(event)

  return events
