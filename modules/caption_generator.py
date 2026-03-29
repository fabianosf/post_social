"""
Módulo de geração de legendas e hashtags via IA.
Suporta múltiplos providers: Groq, OpenAI, Anthropic, Google Gemini, Ollama (local).
Configurável por cliente no config.json via campo "ai_provider".
"""

import os
import json
from typing import Optional


def _build_prompt(
    image_name: str,
    tone: str,
    language: str,
    default_hashtags: list[str] | None = None,
) -> str:
    """Monta o prompt padrão para qualquer provider."""
    description = image_name.rsplit(".", 1)[0]
    description = description.replace("_", " ").replace("-", " ")

    prompt = (
        f"Gere uma legenda criativa para Instagram sobre: '{description}'. "
        f"Tom: {tone}. Idioma: {language}. "
        f"A legenda deve ter no máximo 3 linhas, ser envolvente e terminar com "
        f"um call-to-action sutil. "
        f"Adicione 15 hashtags relevantes ao final (cada uma com #). "
        f"Retorne APENAS a legenda e hashtags, sem explicações."
    )

    if default_hashtags:
        prompt += f"\nInclua obrigatoriamente estas hashtags: {' '.join(default_hashtags)}"

    return prompt


class CaptionGenerator:
    def __init__(self, logger, provider: str = "openai"):
        self.logger = logger
        self.provider = provider.lower()
        self.client = None

        initializers = {
            "groq": self._init_groq,
            "openai": self._init_openai,
            "anthropic": self._init_anthropic,
            "gemini": self._init_gemini,
            "ollama": self._init_ollama,
        }

        init_fn = initializers.get(self.provider)
        if init_fn:
            init_fn()
        else:
            self.logger.warning(
                f"Provider '{provider}' não reconhecido. "
                f"Opções: groq, openai, anthropic, gemini, ollama"
            )

    # ── Inicializadores ──────────────────────────────

    def _init_groq(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            self.logger.warning("GROQ_API_KEY não definida. IA desabilitada.")
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            self.logger.info("Provider Groq inicializado")
        except ImportError:
            self.logger.error("Pacote 'openai' não instalado. pip install openai")

    def _init_openai(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.logger.warning("OPENAI_API_KEY não definida. IA desabilitada.")
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
            self.logger.info("Provider OpenAI inicializado")
        except ImportError:
            self.logger.error("Pacote 'openai' não instalado. pip install openai")

    def _init_anthropic(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.logger.warning("ANTHROPIC_API_KEY não definida. IA desabilitada.")
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self.logger.info("Provider Anthropic inicializado")
        except ImportError:
            self.logger.error("Pacote 'anthropic' não instalado. pip install anthropic")

    def _init_gemini(self):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self.logger.warning("GOOGLE_API_KEY não definida. IA desabilitada.")
            return
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.logger.info("Provider Google Gemini inicializado")
        except ImportError:
            self.logger.error(
                "Pacote 'google-genai' não instalado. pip install google-genai"
            )

    def _init_ollama(self):
        """Ollama roda local, sem API key. Verifica se está acessível."""
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                self.client = "ollama"
                self.logger.info(f"Ollama disponível. Modelos: {', '.join(models[:5])}")
            else:
                self.logger.warning("Ollama não respondeu. Verifique se está rodando.")
        except Exception:
            self.logger.warning(
                "Ollama não acessível em localhost:11434. "
                "Instale: curl -fsSL https://ollama.ai/install.sh | sh && ollama pull llama3.2"
            )

    # ── Geração ──────────────────────────────────────

    def generate(
        self,
        image_name: str,
        tone: str = "profissional e amigável",
        language: str = "pt-br",
        default_hashtags: list[str] | None = None,
    ) -> str:
        if not self.client:
            return self._fallback_caption(image_name, default_hashtags)

        prompt = _build_prompt(image_name, tone, language, default_hashtags)

        generators = {
            "groq": self._generate_groq,
            "openai": self._generate_openai,
            "anthropic": self._generate_anthropic,
            "gemini": self._generate_gemini,
            "ollama": self._generate_ollama,
        }

        gen_fn = generators.get(self.provider)
        if not gen_fn:
            return self._fallback_caption(image_name, default_hashtags)

        try:
            description = image_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
            self.logger.info(f"Gerando legenda via {self.provider} para: {description}")
            caption = gen_fn(prompt)
            self.logger.info(f"Legenda gerada com sucesso via {self.provider}")
            return caption
        except Exception as e:
            self.logger.error(f"Erro no provider {self.provider}: {e}. Usando fallback.")
            return self._fallback_caption(image_name, default_hashtags)

    def generate_multiple(
        self,
        image_name: str,
        count: int = 3,
        tone: str = "profissional e amigável",
        language: str = "pt-br",
        default_hashtags: list[str] | None = None,
    ) -> list[str]:
        """Gera múltiplas opções de legenda para o cliente escolher."""
        if not self.client:
            return [self._fallback_caption(image_name, default_hashtags)]

        description = image_name.rsplit(".", 1)[0]
        description = description.replace("_", " ").replace("-", " ")

        prompt = (
            f"Gere {count} opções DIFERENTES de legenda criativa para Instagram sobre: '{description}'. "
            f"Tom: {tone}. Idioma: {language}. "
            f"Cada legenda deve ter no máximo 3 linhas, ser envolvente e terminar com "
            f"um call-to-action sutil. "
            f"Adicione 10 hashtags relevantes ao final de cada uma (cada uma com #). "
            f"Separe cada opção com '---'. "
            f"Retorne APENAS as legendas separadas por ---, sem numeração ou explicações."
        )

        if default_hashtags:
            prompt += f"\nInclua obrigatoriamente estas hashtags: {' '.join(default_hashtags)}"

        generators = {
            "groq": self._generate_groq,
            "openai": self._generate_openai,
            "anthropic": self._generate_anthropic,
            "gemini": self._generate_gemini,
            "ollama": self._generate_ollama,
        }

        gen_fn = generators.get(self.provider)
        if not gen_fn:
            return [self._fallback_caption(image_name, default_hashtags)]

        try:
            self.logger.info(f"Gerando {count} legendas via {self.provider} para: {description}")
            result = gen_fn(prompt)
            options = [opt.strip() for opt in result.split("---") if opt.strip()]
            self.logger.info(f"{len(options)} legendas geradas via {self.provider}")
            return options if options else [result]
        except Exception as e:
            self.logger.error(f"Erro ao gerar múltiplas legendas: {e}")
            return [self._fallback_caption(image_name, default_hashtags)]

    def _generate_groq(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    def _generate_openai(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    def _generate_anthropic(self, prompt: str) -> str:
        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def _generate_gemini(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip()

    def _generate_ollama(self, prompt: str) -> str:
        import httpx
        resp = httpx.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.2",
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        return resp.json()["response"].strip()

    # ── Fallback ─────────────────────────────────────

    def _fallback_caption(
        self, image_name: str, default_hashtags: list[str] | None = None
    ) -> str:
        description = image_name.rsplit(".", 1)[0]
        description = description.replace("_", " ").replace("-", " ").title()
        hashtags = " ".join(default_hashtags) if default_hashtags else "#post #photo"
        return f"✨ {description}\n\n{hashtags}"
