from src.core.llm_client import AzureModel

SYSTEM_PROMPT = "Você é um assistente útil. Responda em português, de forma objetiva."
MAX_TURNS = 12  # mantém as últimas 12 trocas (user+assistant)

def trim_history(messages):
    # mantém a primeira mensagem (system) e as últimas interações
    system = messages[:1]
    rest = messages[1:]
    keep = rest[-(MAX_TURNS * 2):]  # 2 mensagens por turno
    return system + keep

def main():
    llm = AzureModel(temperature=0.2, max_tokens=300)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    print("Chat iniciado. Comandos: 'sair', 'reset'\n")

    while True:
        user_text = input("Você: ").strip()
        if user_text.lower() in {"sair", "exit", "quit"}:
            print("Encerrando chat.")
            break

        if user_text.lower() == "reset":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("Contexto resetado.\n")
            continue

        messages.append({"role": "user", "content": user_text})

        # evita crescimento infinito
        messages = trim_history(messages)

        try:
            resp = llm.invoke(messages=messages, max_tokens=300)

            assistant_text = resp.choices[0].message.content.strip()
            print(f"Assistente: {assistant_text}\n")

            messages.append({"role": "assistant", "content": assistant_text})

            if getattr(resp, "usage", None):
                print(f"[usage] {resp.usage}\n")

        except Exception as e:
            print("⚠️ Erro ao chamar a LLM:", str(e))
            print("Dica: verifique se o llm_client está usando max_completion_tokens.\n")

if __name__ == "__main__":
    main()