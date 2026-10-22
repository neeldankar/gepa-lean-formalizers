"""Run a formalizer on one item: same sampling settings for every arm (config `generation`)."""
from src.llm import LLMClient
from src.prompting import user_message


def formalizer_client(cfg, model_key, chunk, run_id=None, **kwargs):
    m = cfg["models"][model_key]
    return LLMClient(cfg, chunk, base_url=m["base_url"], api_key_env=m.get("api_key_env"), run_id=run_id,
                     extra_body=m.get("extra_body"), drop_params=m.get("drop_params", ()), limits=m.get("limits"),
                     stream=m.get("stream", False), **kwargs)


def reflection_client(cfg, chunk, run_id=None, **kwargs):
    """GEPA's reflection calls go to the host of the models entry named by gepa.reflection_host
    (Deviation 2: arm F's OpenRouter route, pinned to Together). Only the route is shared: reflection
    keeps its own limits (llm.purpose_limits.reflection), not arm F's."""
    m = cfg["models"][cfg["gepa"]["reflection_host"]]
    return LLMClient(cfg, chunk, base_url=m["base_url"], api_key_env=m.get("api_key_env"), run_id=run_id,
                     extra_body=m.get("extra_body"), drop_params=m.get("drop_params", ()), stream=m.get("stream", False),
                     **kwargs)


def served_name(cfg, model_key):
    return cfg["models"][model_key].get("served_name", model_key)


def generate(client, cfg, model_key, instructions, item, sample=0, fewshot=""):
    """{"text", "usage", "finish_reason"} for one sample."""
    g = cfg["generation"]
    extra = {}
    if "enable_thinking" in cfg["models"][model_key]:
        extra["chat_template_kwargs"] = {"enable_thinking": cfg["models"][model_key]["enable_thinking"]}
    messages = [{"role": "user", "content": user_message(instructions, item, fewshot)}]
    return client.chat_full(served_name(cfg, model_key), messages, purpose="generate", temperature=g["temperature"],
                            max_tokens=g["max_tokens"], seed=g["seed"], sample=sample, extra=extra)
