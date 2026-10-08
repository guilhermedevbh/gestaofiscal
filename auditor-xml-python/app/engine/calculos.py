"""Conferência matemática: Base × Alíquota = Imposto esperado, comparado com o informado (com tolerância)."""


def v(valor) -> float:
    return float(valor or 0.0)


def moeda(valor) -> str:
    if valor is None:
        return "—"
    s = f"{float(valor):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(valor) -> str:
    if valor is None:
        return "—"
    return f"{float(valor):.2f}".replace(".", ",") + "%"


def tolerancia(ctx: dict, esperado: float) -> float:
    """Diferença aceitável = maior entre a tolerância absoluta (R$) e a percentual sobre o esperado."""
    return max(v(ctx.get("tol_abs")), abs(esperado) * v(ctx.get("tol_pct")) / 100.0)


def comparar(informado, base, aliquota, ctx: dict) -> dict:
    """Retorna esperado, diferença e se excede a tolerância. Sem base/alíquota → não comparável."""
    if base is None or aliquota is None:
        return {"comparavel": False, "esperado": None, "diferenca": None, "divergente": False}
    esperado = round(v(base) * v(aliquota) / 100.0, 2)
    diferenca = round(v(informado) - esperado, 2)
    return {"comparavel": True, "esperado": esperado, "diferenca": diferenca,
            "divergente": abs(diferenca) > tolerancia(ctx, esperado) + 1e-9}


def comparar_valores(informado, esperado, ctx: dict) -> dict:
    diferenca = round(v(informado) - v(esperado), 2)
    return {"esperado": round(v(esperado), 2), "diferenca": diferenca,
            "divergente": abs(diferenca) > tolerancia(ctx, v(esperado)) + 1e-9}


def severidade_diferenca(diferenca: float, esperado: float) -> str:
    """Diferença relevante (>5% do esperado ou > R$ 100) é crítica; demais, divergência."""
    from .alertas import CRITICO, DIVERGENCIA
    if abs(diferenca) > 100 or (esperado and abs(diferenca) / abs(esperado) > 0.05):
        return CRITICO
    return DIVERGENCIA
