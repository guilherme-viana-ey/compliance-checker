import os
import logging
from typing import Optional, List, Dict, Union

from dotenv import load_dotenv
import instructor
from openai import AzureOpenAI
from openai.types.chat import ChatCompletion  # tipo correto no SDK v1+

# Carrega as variáveis de ambiente do arquivo .env da raiz do projeto 1
load_dotenv()

# Configuração do logger para este módulo
logger = logging.getLogger(__name__)


class AzureModel:
    """
    Um wrapper para o cliente Azure OpenAI que simplifica a inicialização
    e o uso de chamadas de completion, com suporte opcional para a biblioteca Instructor.
    """

    def __init__(
        self,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        """
        Inicializa o cliente. As configurações são lidas das variáveis de ambiente
        (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, etc.) se não forem passadas diretamente.
        """
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_KEY")
        self.deployment = deployment or os.getenv("AZURE_DEPLOYMENT_NAME")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION")
        self.temperature = temperature
        self.max_tokens = max_tokens

        if not self.endpoint or not self.api_key or not self.deployment:
            logger.error("Configuração do Azure OpenAI incompleta.")
            raise ValueError(
                "As variáveis AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY e AZURE_DEPLOYMENT_NAME"
                " devem estar configuradas no arquivo .env."
            )

        logger.info("Inicializando cliente Azure OpenAI...")
        try:
            base_client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )
            # O cliente 'instructor' adiciona capacidades de extração de dados estruturados
            self.client = instructor.from_openai(base_client)
            self._base_client = base_client
            logger.info("Cliente Azure OpenAI inicializado com sucesso.")
        except Exception:
            logger.exception("Falha ao inicializar o cliente Azure OpenAI.")
            raise

    def invoke(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatCompletion:
        """
        Chama o modelo no formato Chat Completions.

        Você pode usar de 2 formas:
        1) invoke(prompt="...") -> atalho (vira um message de user)
        2) invoke(messages=[{"role":"system","content":"..."}, {"role":"user","content":"..."}])

        Args:
            prompt: Texto simples (atalho).
            messages: Lista de mensagens no formato chat (recomendado).
            system_prompt: Opcional. Se fornecido e messages não tiver 'system', ele será inserido.
            max_tokens: Número máximo de tokens (opcional). (Internamente, pode virar max_completion_tokens)

        Returns:
            O objeto de resposta da API da OpenAI (ChatCompletion).
        """
        if messages is None:
            if prompt is None:
                raise ValueError("Você deve fornecer `prompt` ou `messages`.")
            messages = [{"role": "user", "content": prompt}]

        # Se system_prompt foi passado e não existe uma msg system, insere no começo
        if system_prompt:
            has_system = any(m.get("role") == "system" for m in messages)
            if not has_system:
                messages = [{"role": "system", "content": system_prompt}] + messages

        token_limit = max_tokens or self.max_tokens

        logger.info(f"Invocando modelo '{self.deployment}' no modo chat.")
        try:
            # ✅ Tentativa 1: modelos como gpt-4o (Azure) exigem max_completion_tokens
            response = self._base_client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=self.temperature,
                max_completion_tokens=token_limit,
            )
            logger.info("Resposta recebida do modelo.")
            return response

        except Exception as e:
            # ✅ Fallback: alguns modelos/rotas antigas ainda usam max_tokens
            err_text = str(e).lower()

            # Se o erro for especificamente sobre parâmetro não suportado
            if "unsupported parameter" in err_text and "max_completion_tokens" in err_text:
                logger.warning(
                    "Modelo não suporta max_completion_tokens; tentando com max_tokens (fallback)."
                )
                response = self._base_client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=token_limit,
                )
                logger.info("Resposta recebida do modelo (fallback).")
                return response

            # Se o erro for sobre max_tokens não suportado, deixa explícito no log
            if "unsupported parameter" in err_text and "max_tokens" in err_text:
                logger.error(
                    "Este modelo não suporta max_tokens. Use max_completion_tokens (já tentamos)."
                )

            logger.exception(f"Erro durante a chamada para o modelo '{self.deployment}'.")
            raise
