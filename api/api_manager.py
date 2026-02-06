from threading import Thread
from kivy.clock import Clock

from api.api_bazara import BazaraAPI
from api.api_openfoodfacts import OpenFoodFactsAPI
from api.api_upcitemdb import UPCitemdbAPI
from api.api_sixty60 import Sixty60API


class APIManager:
    """
    Gerencia a busca de produtos em múltiplas APIs.

    Ordem de prioridade:
        1. Bazara        (melhor cobertura para produtos em Moçambique)
        2. Open Food Facts (melhor para alimentos internacionais)
        3. UPCitemdb     (melhor para produtos gerais)
        4. Sixty60       (produtos da África do Sul - Checkers/Shoprite)

    Uso:
        manager = APIManager(on_success=callback_sucesso, on_failure=callback_falha)
        manager.search(barcode)
    """

    # Ordem de busca: lista de tuplas (nome_fonte, instância_da_classe)
    SOURCES = [
        ("Bazara",         BazaraAPI()),
        ("Open Food Facts", OpenFoodFactsAPI()),
        ("UPCitemdb",      UPCitemdbAPI()),
        ("Sixty60",        Sixty60API()),
    ]

    def __init__(self, on_success: callable, on_failure: callable, on_status: callable = None):
        """
        on_success : chamado com (fonte, dados) quando um produto é encontrado.
        on_failure : chamado sem argumentos quando nenhuma API retorna dados.
        on_status  : chamado com (mensagem) durante a busca (opcional).
        """
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_status  = on_status
        self.is_loading = False

    def search(self, barcode: str):
        """Inicia a busca em uma thread separada para não bloquear a UI."""
        if self.is_loading:
            return

        self.is_loading = True
        Thread(target=self._search_all, args=(barcode,), daemon=True).start()

    def _search_all(self, barcode: str):
        """Percorre as fontes na ordem de prioridade até encontrar o produto."""
        try:
            for source_name, api in self.SOURCES:
                self._notify_status(f"Buscando em {source_name}...")

                result = api.fetch(barcode)

                if result:
                    Clock.schedule_once(lambda dt, s=source_name, r=result: self.on_success(s, r), 0)
                    return

            # Nenhuma fonte retornou dados
            Clock.schedule_once(lambda dt: self.on_failure(), 0)

        except Exception as e:
            print(f"[APIManager] Erro inesperado: {e}")
            Clock.schedule_once(lambda dt: self.on_failure(), 0)

        finally:
            self.is_loading = False

    def _notify_status(self, message: str):
        """Enfileira uma atualização de status na thread principal do Kivy."""
        if self.on_status:
            Clock.schedule_once(lambda dt, m=message: self.on_status(m), 0)