#!/usr/bin/env python3
"""
PostSocial - Teste Dry Run (sem postar no Instagram)
Valida: config, pastas, imagens, geração de legenda, logging.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "clients.json"

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name} — {detail}")


def main():
    global PASSED, FAILED

    print("=" * 60)
    print("  PostSocial — Teste Dry Run")
    print("=" * 60)

    # ── 1. Config ──────────────────────────────────────
    print("\n📋 1. Verificando configuração...")

    check("clients.json existe", CONFIG_FILE.exists(), str(CONFIG_FILE))

    if not CONFIG_FILE.exists():
        print("\n⛔ Impossível continuar sem config. Abortando.")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    clients = config.get("clients", [])
    check("Pelo menos 1 cliente configurado", len(clients) > 0, "Lista vazia")

    # ── 2. Pastas por cliente ──────────────────────────
    print("\n📁 2. Verificando pastas dos clientes...")

    for client in clients:
        cid = client["id"]
        print(f"\n  Cliente: {client['name']} ({cid})")

        entrada = BASE_DIR / client["folders"]["entrada"]
        postados = BASE_DIR / client["folders"]["postados"]

        check(f"  Pasta entrada existe ({entrada})", entrada.exists(), "Criar com mkdir -p")
        check(f"  Pasta postados existe ({postados})", postados.exists(), "Criar com mkdir -p")

        # Contar imagens
        if entrada.exists():
            images = [
                f for f in entrada.iterdir()
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
            ]
            check(
                f"  Imagens na pasta entrada: {len(images)}",
                len(images) > 0,
                "Coloque pelo menos 1 imagem para testar",
            )
            for img in images[:3]:
                print(f"       → {img.name} ({img.stat().st_size / 1024:.0f} KB)")

        # Credenciais
        ig = client.get("instagram", {})
        check(
            f"  Username configurado",
            bool(ig.get("username")) and ig["username"] != "loja_exemplo",
            "Substitua 'loja_exemplo' pelo username real",
        )
        check(
            f"  Password configurado",
            bool(ig.get("password")) and ig["password"] != "SENHA_SEGURA_AQUI",
            "Substitua pela senha real",
        )

    # ── 3. Módulos Python ──────────────────────────────
    print("\n🐍 3. Verificando módulos Python...")

    try:
        from modules.logger import setup_logger, setup_global_logger
        check("Módulo logger importado", True)
    except Exception as e:
        check("Módulo logger importado", False, str(e))

    try:
        from modules.file_manager import FileManager
        check("Módulo file_manager importado", True)
    except Exception as e:
        check("Módulo file_manager importado", False, str(e))

    try:
        from modules.instagram_poster import InstagramPoster
        check("Módulo instagram_poster importado", True)
    except Exception as e:
        check("Módulo instagram_poster importado", False, str(e))

    try:
        from modules.caption_generator import CaptionGenerator
        check("Módulo caption_generator importado", True)
    except Exception as e:
        check("Módulo caption_generator importado", False, str(e))

    # ── 4. Logger ──────────────────────────────────────
    print("\n📝 4. Testando sistema de logging...")

    try:
        sys_logger = setup_global_logger(str(BASE_DIR))
        sys_logger.info("Teste de log do sistema")
        check("Logger global funcional", True)

        log_file = BASE_DIR / "logs"
        check("Pasta logs/ criada", log_file.exists())
    except Exception as e:
        check("Logger global funcional", False, str(e))

    if clients:
        try:
            test_client = clients[0]
            cl_logger = setup_logger(test_client["id"], str(BASE_DIR))
            cl_logger.info("Teste de log do cliente")
            check(f"Logger cliente '{test_client['id']}' funcional", True)
        except Exception as e:
            check("Logger cliente funcional", False, str(e))

    # ── 5. File Manager ──────────────────────────────
    print("\n📂 5. Testando FileManager...")

    if clients:
        test_client = clients[0]
        cl_logger = setup_logger(test_client["id"], str(BASE_DIR))
        fm = FileManager(
            entrada_dir=str(BASE_DIR / test_client["folders"]["entrada"]),
            postados_dir=str(BASE_DIR / test_client["folders"]["postados"]),
            logger=cl_logger,
        )
        next_img = fm.get_next_image()
        pending = fm.count_pending()
        check(f"FileManager inicializado (pendentes: {pending})", True)
        if next_img:
            print(f"       → Próxima imagem: {next_img.name}")

    # ── 6. Geração de Legenda ─────────────────────────
    print("\n🤖 6. Testando geração de legenda...")

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        check("ANTHROPIC_API_KEY definida", True)
        try:
            cl_logger = setup_logger("test", str(BASE_DIR))
            gen = CaptionGenerator(cl_logger)
            caption = gen.generate(
                image_name="cafe_artesanal_especial.jpg",
                tone="profissional e amigável",
                language="pt-br",
                default_hashtags=["#cafe", "#artesanal"],
            )
            check("Legenda IA gerada com sucesso", bool(caption))
            print(f"\n       Legenda gerada:\n       {'─' * 40}")
            for line in caption.split("\n"):
                print(f"       {line}")
            print(f"       {'─' * 40}")
        except Exception as e:
            check("Legenda IA gerada", False, str(e))
    else:
        print("  ⚠️  ANTHROPIC_API_KEY não definida — testando fallback")
        cl_logger = setup_logger("test", str(BASE_DIR))
        gen = CaptionGenerator(cl_logger)
        caption = gen._fallback_caption(
            "cafe_artesanal_especial.jpg", ["#cafe", "#artesanal"]
        )
        check("Legenda fallback gerada", bool(caption))
        print(f"       → {caption}")

    # ── 7. Dependências ───────────────────────────────
    print("\n📦 7. Verificando dependências...")

    try:
        import instagrapi
        check(f"instagrapi v{instagrapi.__version__}", True)
    except Exception as e:
        check("instagrapi instalado", False, str(e))

    try:
        import anthropic
        check(f"anthropic v{anthropic.__version__}", True)
    except Exception as e:
        check("anthropic instalado", False, str(e))

    try:
        import PIL
        check(f"Pillow v{PIL.__version__}", True)
    except Exception as e:
        check("Pillow instalado", False, str(e))

    # ── Resultado Final ───────────────────────────────
    total = PASSED + FAILED
    print("\n" + "=" * 60)
    print(f"  Resultado: {PASSED}/{total} testes passaram")
    if FAILED == 0:
        print("  🎉 Tudo pronto! Próximo passo: testar login real.")
        print("     Execute: python test_login.py")
    else:
        print(f"  ⚠️  {FAILED} teste(s) falharam. Corrija antes de continuar.")
    print("=" * 60)


if __name__ == "__main__":
    main()
