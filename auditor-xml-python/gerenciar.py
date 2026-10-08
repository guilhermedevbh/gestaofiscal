"""Gerenciamento local do serviço.

  python gerenciar.py inicializar                 → cria o banco e o primeiro administrador (mostra o token uma única vez)
  python gerenciar.py criar-usuario NOME PERFIL   → PERFIL: admin | analista | consulta
  python gerenciar.py usuarios                    → lista usuários
  python gerenciar.py desativar NOME              → revoga o acesso (o histórico é mantido)
  python gerenciar.py servidor                    → inicia a API (http://127.0.0.1:8765)
"""
import sys

from app import config, database
from app.security import gerar_token, hash_token


def _criar(nome: str, perfil: str) -> None:
    token = gerar_token()
    database.criar_usuario(nome, perfil, hash_token(token))
    database.registrar_historico("console", "USUARIO_CRIADO", resultado="OK", detalhes={"usuario": nome, "perfil": perfil})
    print(f"\nUsuário '{nome}' ({perfil}) criado.\nTOKEN DE ACESSO (guarde agora, não será exibido novamente):\n\n  {token}\n")


def main(argv):
    database.inicializar()
    cmd = argv[1] if len(argv) > 1 else "ajuda"
    if cmd == "inicializar":
        if database.total_usuarios():
            print("O serviço já possui usuários. Use 'criar-usuario' para adicionar outros.")
            return 0
        nome = input("Nome do administrador: ").strip() or "Administrador"
        _criar(nome, "admin")
        return 0
    if cmd == "criar-usuario" and len(argv) >= 4:
        if argv[3] not in config.PERFIS:
            print("Perfil inválido. Use: " + ", ".join(config.PERFIS))
            return 1
        _criar(argv[2], argv[3])
        return 0
    if cmd == "usuarios":
        for u in database.listar_usuarios():
            print(f"{u['nome']:<30} {u['perfil']:<10} {'ativo' if u['ativo'] else 'desativado'}  desde {u['criado_em']}")
        return 0
    if cmd == "desativar" and len(argv) >= 3:
        ok = database.desativar_usuario(argv[2])
        database.registrar_historico("console", "USUARIO_DESATIVADO", resultado="OK" if ok else "NAO_ENCONTRADO", detalhes={"usuario": argv[2]})
        print("Usuário desativado." if ok else "Usuário não encontrado.")
        return 0 if ok else 1
    if cmd == "servidor":
        from app.server import iniciar
        iniciar()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
