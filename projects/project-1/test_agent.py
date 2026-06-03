import sys
sys.path.insert(0, ".")

from src.agents.tools import tool_read_document, tool_analyze_compliance

# Testa leitura
text, profile = tool_read_document("data/input/recomendacao_01.txt")
print(f"Perfil: {profile}")
print(f"Texto: {text[:100]}")

# Testa análise
result = tool_analyze_compliance(text, profile)
print(f"Compliant: {result.is_compliant}")
print(f"Motivo: {result.reason[:100]}")