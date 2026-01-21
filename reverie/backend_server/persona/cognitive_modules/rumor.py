import datetime
import random
import re
from dataclasses import dataclass

from text_sanitize import world_sanitize
SEED_EMBEDDING_DIM = 1536

LOCATION_ALIAS = {
  "Isabella Rodriguez's apartment": "怡红院",
  "Dorm for Oak Hill College": "潇湘馆",
  "The Rose and Crown Pub": "蘅芜苑",
  "Johnson Park": "沁芳亭",
  "Harvey Oak Supply Store": "稻香村",
}

LOCATION_BY_ALIAS = {v: k for k, v in LOCATION_ALIAS.items()}

TRIGGER_KEYWORDS = [
  "沁芳亭",
  "潇湘馆",
  "怡红院",
  "蘅芜苑",
  "稻香村",
  "宝玉",
  "黛玉",
  "宝钗",
]


@dataclass
class Rumor:
  content: str
  origin: str
  credibility: float
  mutation_count: int
  targets: list
  timestamp: str

  def to_memory_description(self):
    safe_targets = ",".join(self.targets) if self.targets else ""
    return (
      f"【流言】听闻{self.content}｜origin={self.origin}"
      f"｜cred={self.credibility:.2f}｜mut={self.mutation_count}"
      f"｜targets={safe_targets}｜ts={self.timestamp}"
    )


def rumor_from_description(description):
  if not description.startswith("【流言】"):
    return None
  parts = description.split("｜")
  if not parts:
    return None
  content = parts[0].replace("【流言】听闻", "").strip()
  fields = {}
  for part in parts[1:]:
    if "=" in part:
      k, v = part.split("=", 1)
      fields[k.strip()] = v.strip()
  try:
    credibility = float(fields.get("cred", "0.5"))
    mutation_count = int(fields.get("mut", "0"))
    targets = [t for t in fields.get("targets", "").split(",") if t]
    timestamp = fields.get("ts", "")
    origin = fields.get("origin", "")
  except ValueError:
    return None
  return Rumor(content, origin, credibility, mutation_count, targets, timestamp)


def _seed_embedding(seed_text):
  rng = random.Random(hash(seed_text))
  return [rng.random() for _ in range(SEED_EMBEDDING_DIM)]


def _keywords_from_content(content):
  keywords = set()
  for kw in TRIGGER_KEYWORDS:
    if kw in content:
      keywords.add(kw)
  for token in re.split(r"[，。；：、\s]+", content):
    token = token.strip()
    if len(token) >= 2:
      keywords.add(token)
  return list(keywords)


def _trigger_boost(text):
  boost = 0.0
  for kw in TRIGGER_KEYWORDS:
    if kw in text:
      boost += 0.05
  return boost


def _mutate_content(content):
  if "听闻" in content:
    return content.replace("听闻", "据说", 1)
  if "似乎" not in content and "好像" not in content:
    return content.replace("在", "似乎在", 1)
  return content.replace("似乎", "仿佛", 1)


def _location_phrase(curr_loc):
  if curr_loc in LOCATION_ALIAS:
    return f"{LOCATION_ALIAS[curr_loc]}（{curr_loc}）"
  return curr_loc


def _extract_topic(convo_summary):
  topic = convo_summary.strip()
  if topic.startswith("conversing about"):
    topic = topic.replace("conversing about", "").strip()
  if re.search(r"[A-Za-z]", topic):
    topic = "园中诗话"
  if not topic:
    topic = "园中近来逸事"
  return topic


def maybe_generate_rumor(init_persona, target_persona, curr_loc, convo_summary):
  base_prob = 1.0
  base_prob += _trigger_boost(convo_summary)
  if random.random() > min(base_prob, 1.0):
    return None

  timestamp = init_persona.scratch.curr_time.strftime("%Y-%m-%d %H:%M:%S")
  topic = _extract_topic(convo_summary)
  location = _location_phrase(curr_loc)
  content = f"{init_persona.name}与{target_persona.name}在{location}似乎提到{topic}"
  content = world_sanitize(content)
  credibility = max(0.3, 0.8 - _trigger_boost(content))
  targets = [init_persona.name, target_persona.name]
  return Rumor(content, init_persona.name, credibility, 0, targets, timestamp)


def maybe_mutate_rumor(rumor):
  if random.random() > 0.9:
    return rumor
  content = _mutate_content(rumor.content)
  content = world_sanitize(content)
  credibility = max(0.1, rumor.credibility - 0.1)
  return Rumor(content, rumor.origin, credibility, rumor.mutation_count + 1, rumor.targets, rumor.timestamp)


def add_rumor_memory(persona, rumor):
  description = world_sanitize(rumor.to_memory_description())
  keywords = _keywords_from_content(rumor.content)
  keywords += ["流言", "听闻"]
  embedding_pair = (description, _seed_embedding(description))
  return persona.a_mem.add_event(
    persona.scratch.curr_time,
    None,
    persona.name,
    "heard",
    "rumor",
    description,
    keywords,
    3,
    embedding_pair,
    None,
  )


def maybe_spread_rumor(speaker, listener):
  rumor_nodes = [n for n in speaker.a_mem.seq_event if n.description.startswith("【流言】")]
  if not rumor_nodes:
    return None
  rumor = rumor_from_description(rumor_nodes[0].description)
  if rumor is None:
    return None

  prob = 0.35 + _trigger_boost(rumor.content)
  if random.random() > min(prob, 0.6):
    return None
  mutated = maybe_mutate_rumor(rumor)
  mutated = Rumor(
    world_sanitize(mutated.content),
    mutated.origin,
    mutated.credibility,
    mutated.mutation_count,
    mutated.targets,
    mutated.timestamp,
  )
  add_rumor_memory(listener, mutated)
  return mutated


def spread_rumor_to_listener(rumor, speaker, listener):
  mutated = maybe_mutate_rumor(rumor)
  mutated = Rumor(
    world_sanitize(mutated.content),
    mutated.origin,
    mutated.credibility,
    mutated.mutation_count,
    mutated.targets,
    mutated.timestamp,
  )
  add_rumor_memory(listener, mutated)
  return mutated


def maybe_influence_action(persona, act_desp, act_dura):
  rumor_nodes = [n for n in persona.a_mem.seq_event if n.description.startswith("【流言】")]
  if not rumor_nodes:
    return None
  if getattr(persona.scratch, "rumor_influence_done", False):
    return None
  rumor = rumor_from_description(rumor_nodes[0].description)
  if rumor is None:
    return None

  chosen_loc = None
  for alias, loc in LOCATION_BY_ALIAS.items():
    if alias in rumor.content:
      chosen_loc = (alias, loc)
      break
  if not chosen_loc:
    return None

  alias, loc = chosen_loc
  new_act_desp = world_sanitize(f"去{alias}（{loc}）看看传闻的来处")
  new_act_dura = min(30, act_dura)
  persona.scratch.rumor_influence_done = True
  return {
    "rumor": rumor,
    "act_description": new_act_desp,
    "act_duration": new_act_dura,
  }
