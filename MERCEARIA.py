"""Ponto de entrada legado do sistema desktop unificado."""

from admin_app import StoreApp


# Alguns atalhos antigos ainda apontam para este ficheiro. Eles agora abrem a
# mesma sessao unica usada pelos pontos de entrada desktop atuais.
MainApp = StoreApp


if __name__ == '__main__':
    try:
        StoreApp().run()
    except KeyboardInterrupt:
        pass
