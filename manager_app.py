"""Ponto de entrada de compatibilidade para o aplicativo desktop unico."""

from admin_app import StoreApp


# Atalhos antigos do gerente passam a abrir a mesma aplicacao e a mesma tela
# de login do administrador. O perfil autenticado define o painel inicial.
ManagerApp = StoreApp


if __name__ == '__main__':
    try:
        StoreApp().run()
    except KeyboardInterrupt:
        pass
