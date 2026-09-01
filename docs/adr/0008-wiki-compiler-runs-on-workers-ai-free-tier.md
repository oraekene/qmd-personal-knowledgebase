# 0008-provider-agnostic-synthesis-inference.md

# Provider-agnostic synthesis inference via OpenAI-compatible endpoints

The Wiki Compiler's LLM calls route through any OpenAI-compatible endpoint,
configured via environment variables (base URL, API key, model name). The
default is Cloudflare Workers AI's free tier (10,000 Neurons/day, zero
data retention) using Llama-3.1-8b-instruct-fp8-fast. The provider is a
configuration knob, not an architectural commitment: upgrading to a
higher-quality model (GLM-5.2, GPT-class, etc.) via any OpenAI-compatible
provider requires only an env-var change. Free-tier providers that train
on inference data are rejected for synthesis passes — the corpus is
personal knowledge, and privacy is a hard constraint on this layer.